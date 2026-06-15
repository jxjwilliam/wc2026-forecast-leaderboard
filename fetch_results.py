"""
fetch_results.py — Daily: pull real match results from football-data.org API.

Strategy: Fetch all matches for competition 2000 (FIFA World Cup 2026),
map API English team names to canonical Chinese names via TEAM_MAP,
and upsert FINISHED match scores into the results table.
"""

import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
import requests

from parse_forecasts import normalise_team

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API")
API_BASE = "https://api.football-data.org/v4"
DB_PATH = "forecasts.db"
COMPETITION_ID = 2000  # FIFA World Cup


def fetch_finished_matches() -> list[dict]:
    """Fetch all FINISHED matches for the World Cup from football-data.org."""
    url = f"{API_BASE}/competitions/{COMPETITION_ID}/matches"
    headers = {"X-Auth-Token": API_KEY}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    all_matches = resp.json()["matches"]
    return [m for m in all_matches if m["status"] == "FINISHED"]


def build_local_match_index(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """Build {(home_cn, away_cn): match_row} from the local matches table."""
    cur = conn.execute(
        "SELECT id, group_name, home_team, away_team FROM matches"
    )
    index: dict[tuple[str, str], dict] = {}
    for row in cur.fetchall():
        match_id, group_name, home, away = row
        index[(home, away)] = {"id": match_id, "group": group_name}
    return index


def upsert_result(conn: sqlite3.Connection, match_id: int,
                  home_score: int, away_score: int) -> None:
    """Insert or replace a result row."""
    conn.execute(
        """INSERT OR REPLACE INTO results (match_id, home_score, away_score)
           VALUES (?, ?, ?)""",
        (match_id, home_score, away_score),
    )


def main() -> None:
    if not API_KEY:
        print("ERROR: FOOTBALL_DATA_API env var not set.")
        return

    print(f"=== Fetching results — {datetime.now().date()} ===")

    # 1. Fetch finished matches from API
    print("Fetching finished matches from football-data.org...")
    finished_matches = fetch_finished_matches()
    print(f"  Found {len(finished_matches)} FINISHED matches")

    if not finished_matches:
        print("  Nothing to do.")
        return

    # 2. Build local match index
    conn = sqlite3.connect(DB_PATH)
    local_index = build_local_match_index(conn)

    # 3. Match API results to local matches
    inserted = 0
    skipped = 0
    for m in finished_matches:
        home_api = m["homeTeam"]["name"]
        away_api = m["awayTeam"]["name"]
        home_cn = normalise_team(home_api)
        away_cn = normalise_team(away_api)

        if home_cn == home_api or away_cn == away_api:
            print(f"  SKIP: unmapped team ({home_api} vs {away_api})")
            skipped += 1
            continue

        # Try as-is, then swapped (API home/away may differ from canonical)
        key = (home_cn, away_cn)
        local = local_index.get(key)
        swapped = False
        if local is None:
            key_rev = (away_cn, home_cn)
            local = local_index.get(key_rev)
            if local is not None:
                swapped = True

        if local is None:
            print(f"  SKIP: no match in DB for {home_cn} vs {away_cn}")
            skipped += 1
            continue

        if swapped:
            home_score = m["score"]["fullTime"]["away"]
            away_score = m["score"]["fullTime"]["home"]
        else:
            home_score = m["score"]["fullTime"]["home"]
            away_score = m["score"]["fullTime"]["away"]

        if home_score is None or away_score is None:
            print(f"  SKIP: {home_cn} vs {away_cn} — null score")
            skipped += 1
            continue

        try:
            upsert_result(conn, local["id"], home_score, away_score)
            conn.commit()
            print(f"  OK: {home_cn} {home_score}-{away_score} {away_cn}")
            inserted += 1
        except sqlite3.Error as e:
            print(f"  ERROR: {e}")
            conn.rollback()
            skipped += 1

    print(f"\nDone: {inserted} results stored, {skipped} skipped")
    conn.close()


if __name__ == "__main__":
    main()
