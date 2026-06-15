"""
report.py — Daily: generate a self-contained HTML report with charts.

Report sections:
  1. Leaderboard (ranked table: model | exact scores | correct results | total pts | % accuracy)
  2. Today's matches (side-by-side prediction vs real result per model)
  3. Running accuracy chart (matplotlib PNG embedded in HTML)
  4. Betting signal (best model based on last 5 matches)
  5. Surprise flag (matches where no model predicted the result)
"""

import sqlite3
from pathlib import Path

DB_PATH = "forecasts.db"
REPORT_DIR = Path("reports")


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    print("Generating daily report...")
    # TODO: query scores from forecasts.db
    # TODO: build leaderboard
    # TODO: build match comparison table
    # TODO: generate accuracy-over-time chart (matplotlib)
    # TODO: compute betting signal from last 5 matches
    # TODO: flag surprise matches
    # TODO: write self-contained HTML to reports/
    print("Report saved.")


if __name__ == "__main__":
    main()
