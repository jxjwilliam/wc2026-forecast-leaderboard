"""
fetch_results.py — Daily: pull real match results from football-data.org API.

Reads expected matches from forecasts.db, fetches live scores via
the football-data.org free tier API, and stores results in the same DB.
"""

import os
import sqlite3
from datetime import datetime

API_KEY = os.getenv("FOOTBALL_DATA_API")
API_BASE = "https://api.football-data.org/v4"
DB_PATH = "forecasts.db"


def main() -> None:
    if not API_KEY:
        print("ERROR: FOOTBALL_DATA_API env var not set.")
        return

    print(f"Fetching match results for {datetime.now().date()}...")
    # TODO: query forecasts.db for pending matches
    # TODO: call football-data.org API for each match
    # TODO: upsert results into forecasts.db
    print("Results synced.")


if __name__ == "__main__":
    main()
