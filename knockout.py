"""
knockout.py — Group stage → knockout simulation.

Uses the current leader model's predictions for unplayed group matches,
computes group standings, determines the 32 qualifiers, then simulates
the knockout bracket by comparing group stage performance.

Outputs:
  - reports/knockout-{date}.html  (visual bracket)
  - Text summary (returned for pipeline / Telegram)
"""

import sqlite3
from collections import OrderedDict
from datetime import date
from pathlib import Path

DB_PATH = "forecasts.db"
REPORT_DIR = Path("reports")

# Groups A–L
ALL_GROUPS = [chr(ord("A") + i) for i in range(12)]


# ─── Step 1: Identify leader model ───────────────────────────────────────────

def find_leader(conn: sqlite3.Connection) -> tuple[int, str] | None:
    """Return (model_id, display_name) of the current leader by avg score."""
    cur = conn.execute("""
        SELECT m.id, m.display_name
        FROM scores s
        JOIN predictions p ON p.id = s.prediction_id
        JOIN models m ON m.id = p.model_id
        GROUP BY m.id
        ORDER BY AVG(s.total) DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    return (row[0], row[1]) if row else None


# ─── Step 2: Compute group standings ─────────────────────────────────────────

TeamStats = dict[str, int | float | str]  # typed for clarity


def _empty_stats(team: str) -> TeamStats:
    return {
        "team": team,
        "pld": 0,
        "w": 0, "d": 0, "l": 0,
        "gf": 0, "ga": 0,
        "gd": 0, "pts": 0,
    }


def compute_group_standings(conn: sqlite3.Connection,
                            leader_id: int) -> dict[str, list[TeamStats]]:
    """Return {group_name: [team_stats_sorted]} for all 12 groups."""
    from parse_forecasts import normalise_team

    # Load all matches
    cur = conn.execute("""
        SELECT id, group_name, home_team, away_team
        FROM matches
        WHERE stage = 'group'
        ORDER BY group_name, match_number
    """)
    matches = cur.fetchall()

    # Load all results
    cur = conn.execute("SELECT match_id, home_score, away_score FROM results")
    results = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # Load all leader predictions
    cur = conn.execute("""
        SELECT match_id, home_score, away_score
        FROM predictions
        WHERE model_id = ?
    """, (leader_id,))
    predictions = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # Per group, build team stats
    groups: dict[str, dict[str, TeamStats]] = {}
    missed_predictions = 0
    for mid, group, home, away in matches:
        if group not in groups:
            groups[group] = OrderedDict()
        g = groups[group]
        if home not in g:
            g[home] = _empty_stats(home)
        if away not in g:
            g[away] = _empty_stats(away)

        # Use actual result if available, else leader prediction
        if mid in results:
            hs, as_ = results[mid]
        elif mid in predictions:
            hs, as_ = predictions[mid]
        else:
            missed_predictions += 1
            continue

        g[home]["pld"] += 1
        g[away]["pld"] += 1
        g[home]["gf"] += hs
        g[home]["ga"] += as_
        g[away]["gf"] += as_
        g[away]["ga"] += hs

        if hs > as_:
            g[home]["w"] += 1
            g[away]["l"] += 1
            g[home]["pts"] += 3
        elif hs < as_:
            g[away]["w"] += 1
            g[home]["l"] += 1
            g[away]["pts"] += 3
        else:
            g[home]["d"] += 1
            g[away]["d"] += 1
            g[home]["pts"] += 1
            g[away]["pts"] += 1

    if missed_predictions:
        print(f"  [knockout] WARNING: {missed_predictions} matches without result or prediction")

    # Sort each group
    result: dict[str, list[TeamStats]] = {}
    for group, teams in groups.items():
        sorted_teams = sorted(
            teams.values(),
            key=lambda t: (t["pts"], t["gf"] - t["ga"], t["gf"], t["team"]),
            reverse=True,
        )
        for i, t in enumerate(sorted_teams, start=1):
            t["position"] = i
            t["gd"] = t["gf"] - t["ga"]
        result[group] = sorted_teams

    return result


# ─── Step 3: Determine qualifiers ────────────────────────────────────────────

QualifierInfo = tuple[str, str, int, int, int, int, str]
# (group, team, position, pts, gd, gf, source)


def determine_qualifiers(
    standings: dict[str, list[TeamStats]],
) -> tuple[list[QualifierInfo], list[QualifierInfo], list[QualifierInfo]]:
    """Return (winners, runners_up, third_place_sorted)."""
    winners: list[QualifierInfo] = []
    runners_up: list[QualifierInfo] = []
    third_places: list[QualifierInfo] = []

    for group in ALL_GROUPS:
        if group not in standings:
            continue
        teams = standings[group]
        for i, t in enumerate(teams):
            info = (group, t["team"], t["position"], t["pts"], t["gd"], t["gf"], "group")
            if i == 0:
                winners.append(info)
            elif i == 1:
                runners_up.append(info)
            elif i == 2:
                third_places.append(info)

    # Sort third places and take top 8
    third_places.sort(key=lambda x: (x[3], x[4], x[5]), reverse=True)
    best_third = third_places[:8]

    return winners, runners_up, best_third


# ─── Step 4: Simulate knockout bracket ───────────────────────────────────────

def simulate_match(team_a: QualifierInfo, team_b: QualifierInfo) -> QualifierInfo:
    """Compare two teams' group records. Return the winner."""
    # Compare: points → GD → GF
    a_key = (team_a[3], team_a[4], team_a[5])
    b_key = (team_b[3], team_b[4], team_b[5])
    if a_key >= b_key:
        return team_a
    return team_b


def simulate_round(matches: list[tuple[QualifierInfo, QualifierInfo]]) -> list[QualifierInfo]:
    """Simulate all matches in a round. Return list of winners."""
    return [simulate_match(a, b) for a, b in matches]


def simulate_bracket(qualifiers: tuple[list[QualifierInfo], list[QualifierInfo], list[QualifierInfo]]) -> dict:
    """Run the full bracket simulation. Return structured bracket data."""

    winners, runners_up, best_third = qualifiers

    # Combine all 32 teams sorted by performance
    # Winners: positions 1-12, Runners-up: 13-24, 3rd-place: 25-32
    # But we sort interleaved by actual performance for fair bracket seeding

    # Actually, seed by performance: all qualifiers sorted by group record
    all_qualifiers = winners + runners_up + best_third
    all_qualifiers.sort(key=lambda x: (x[3], x[4], x[5]), reverse=True)

    # R32: 1 vs 32, 2 vs 31, ..., 16 vs 17
    n = len(all_qualifiers)
    r32_matches = []
    for i in range(n // 2):
        r32_matches.append((all_qualifiers[i], all_qualifiers[n - 1 - i]))

    winners_r32 = simulate_round(r32_matches)

    # R16: winner 1 vs winner 16, winner 2 vs winner 15, etc.
    r16_matches = []
    for i in range(len(winners_r32) // 2):
        r16_matches.append((winners_r32[i], winners_r32[len(winners_r32) - 1 - i]))
    winners_r16 = simulate_round(r16_matches)

    # QF
    qf_matches = []
    for i in range(len(winners_r16) // 2):
        qf_matches.append((winners_r16[i], winners_r16[len(winners_r16) - 1 - i]))
    winners_qf = simulate_round(qf_matches)

    # SF
    sf_matches = [(winners_qf[0], winners_qf[1]), (winners_qf[2], winners_qf[3])]
    winners_sf = simulate_round(sf_matches)

    # 3rd-place playoff
    third_place_match = (winners_sf[0], winners_sf[1])  # not quite
    # SF losers play 3rd-place
    sf_losers = []
    for a, b in sf_matches:
        a_key = (a[3], a[4], a[5])
        b_key = (b[3], b[4], b[5])
        if a_key >= b_key:
            sf_losers.append(b)
        else:
            sf_losers.append(a)
    third_place_winner = simulate_match(sf_losers[0], sf_losers[1])

    # Final
    champion = simulate_match(winners_sf[0], winners_sf[1])
    runner_up = winners_sf[1] if (winners_sf[0][3], winners_sf[0][4], winners_sf[0][5]) >= (winners_sf[1][3], winners_sf[1][4], winners_sf[1][5]) else winners_sf[0]

    return {
        "champion": champion,
        "runner_up": runner_up,
        "third": third_place_winner,
        "rounds": {
            "R32": r32_matches,
            "R16": r16_matches,
            "QF": qf_matches,
            "SF": sf_matches,
        },
        "all_qualifiers": all_qualifiers,
    }


# ─── Step 5: Generate HTML bracket page ──────────────────────────────────────

def _t_short(info: QualifierInfo) -> str:
    """Short team label with record."""
    return f"{info[1]} ({info[3]}pts, GD{info[4]:+d})"


def _t_name(info: QualifierInfo) -> str:
    return info[1]


def generate_html(bracket: dict, leader_name: str) -> str:
    """Return self-contained HTML bracket page."""

    rounds_html = ""
    round_labels = {"R32": "Round of 32", "R16": "Round of 16",
                    "QF": "Quarter-finals", "SF": "Semi-finals"}

    for rnd_name, rnd_label in round_labels.items():
        matches = bracket["rounds"][rnd_name]
        matches_html = ""
        for a, b in matches:
            winner = simulate_match(a, b)
            loser = b if winner == a else a
            matches_html += f"""<tr>
    <td class="team {'winner' if winner == a else ''}">{_t_name(a)}</td>
    <td class="vs">vs</td>
    <td class="team {'winner' if winner == b else ''}">{_t_name(b)}</td>
    <td class="result">→ {_t_name(winner)}</td>
</tr>
"""
        rounds_html += f"""<h2>{rnd_label}</h2>
<table>
<tr><th>Home</th><th></th><th>Away</th><th>Advances</th></tr>
{matches_html}
</table>
"""

    champ = bracket["champion"]
    runner = bracket["runner_up"]
    third = bracket["third"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚽</text></svg>">
<title>WC2026 Knockout Prediction — {date.today()}</title>
<style>
  body {{
    font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
    max-width: 900px; margin: 0 auto; padding: 20px;
    background: #f5f7fa; color: #333;
  }}
  h1 {{ margin: 0; font-size: 1.4em; }}
  .logo {{ color: #1a1a2e; text-decoration: none; }}
  .logo:hover {{ text-decoration: underline; }}
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 3px solid #e94560; padding-bottom: 10px; margin-bottom: 16px;
    flex-wrap: wrap; gap: 8px;
  }}
  .nav {{
    display: flex; gap: 6px; flex-wrap: wrap;
  }}
  .nav a {{
    display: inline-block; padding: 7px 14px;
    background: #1a1a2e; color: #fff; border-radius: 6px;
    font-size: 0.85em; text-decoration: none; font-family: inherit; white-space: nowrap;
  }}
  .nav a:hover {{ opacity: 0.9; }}
  h2 {{ color: #1a1a2e; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0;
           background: #fff; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  th {{ background: #1a1a2e; color: #fff; padding: 8px; text-align: center; }}
  td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; }}
  .team {{ font-weight: 500; }}
  .winner {{ color: #1a7a1a; font-weight: bold; }}
  .vs {{ color: #999; }}
  .result {{ font-size: 0.9em; color: #555; }}
  .podium {{ text-align: center; margin: 20px 0; }}
  .podium h2 {{ margin-bottom: 4px; }}
  .gold {{ color: #b8860b; font-size: 1.8em; font-weight: bold; }}
  .silver {{ color: #7a7a7a; font-size: 1.4em; }}
  .bronze {{ color: #cd7f32; font-size: 1.2em; }}
  footer {{ margin-top: 30px; font-size: 0.8em; color: #888; text-align: center; }}
  .leader-note {{ background: #eef; padding: 10px 16px; border-radius: 8px;
                  margin: 16px 0; font-size: 0.9em; }}
</style>
</head>
<body>
<div class="header">
  <h1><a href="/" class="logo">🏆 Knockout Prediction — {date.today()}</a></h1>
  <div class="nav">
    <a href="/latest">📊 Report</a>
    <a href="/knockout">🏆 Bracket</a>
    <a href="/chat">💬 Chat</a>
  </div>
</div>

<div class="leader-note">
  Simulation based on <strong>{leader_name}</strong> predictions for unplayed group matches.
  Teams are seeded by group stage performance (points → goal difference → goals scored).
</div>

<div class="podium">
  <div class="gold">🥇 {_t_name(champ)}</div>
  <div class="silver">🥈 {_t_name(runner)}</div>
  <div class="bronze">🥉 {_t_name(third)}</div>
</div>

{rounds_html}

<footer>Generated by WC2026 Forecast Tracker · Knockout Simulation</footer>
</body>
</html>"""


# ─── Step 6: Generate Telegram summary ───────────────────────────────────────

def generate_summary(bracket: dict, leader_name: str) -> str | None:
    """Return a short Telegram-friendly summary string."""
    champ = bracket["champion"]
    runner = bracket["runner_up"]
    third = bracket["third"]
    n_qualifiers = len(bracket["all_qualifiers"])

    lines = [
        f"🏆 <b>Knockout Prediction</b> (based on {leader_name})",
        f"",
        f"Groups decided: {n_qualifiers} teams advance to knockouts",
        f"",
        f"🥇 {champ[1]} — Predicted Champion",
        f"🥈 {runner[1]} — Runner-up",
        f"🥉 {third[1]} — Third place",
    ]
    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> str | None:
    REPORT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    leader = find_leader(conn)
    if leader is None:
        print("[knockout] No scores yet — cannot determine leader. Skipping.")
        conn.close()
        return None

    leader_id, leader_name = leader
    print(f"[knockout] Leader: {leader_name}")

    standings = compute_group_standings(conn, leader_id)
    if not standings:
        print("[knockout] No group standings computed. Skipping.")
        conn.close()
        return None

    # Print group standings summary
    for group in ALL_GROUPS:
        if group not in standings:
            continue
        print(f"  Group {group}:")
        for t in standings[group]:
            print(f"    {t['position']}. {t['team']} — {t['pts']}pts ({t['w']}W/{t['d']}D/{t['l']}L) "
                  f"GD{t['gd']:+d} GF={t['gf']}")
        print()

    qualifiers = determine_qualifiers(standings)
    winners, runners_up, best_third = qualifiers
    print(f"[knockout] Qualifiers: {len(winners)} group winners, "
          f"{len(runners_up)} runners-up, {len(best_third)} third-place")
    if best_third:
        print(f"  Best 3rd-place teams (qualifying):")
        for t in best_third:
            print(f"    {t[1]} (Group {t[0]}) — {t[3]}pts")

    bracket = simulate_bracket(qualifiers)
    print(f"\n[knockout] Champion: {bracket['champion'][1]}")
    print(f"[knockout] Runner-up: {bracket['runner_up'][1]}")
    print(f"[knockout] Third: {bracket['third'][1]}")

    # Generate HTML
    html = generate_html(bracket, leader_name)
    out_path = REPORT_DIR / f"knockout-{date.today()}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"[knockout] Bracket saved: {out_path} ({len(html):,} bytes)")

    conn.close()

    # Return Telegram summary
    summary = generate_summary(bracket, leader_name)
    print(f"[knockout] Summary:\n{summary}")
    return summary


if __name__ == "__main__":
    main()
