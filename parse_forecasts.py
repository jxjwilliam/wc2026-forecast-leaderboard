"""
parse_forecasts.py — One-time ingestion of all 4 LLM forecast files into SQLite.

Reads forecast data from data/ directory (claude.pdf, gemini.md, chatgpt.md, doubao.md),
normalises into a standard schema, and inserts into forecasts.db.
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path("data")
DB_PATH = "forecasts.db"


def main() -> None:
    print("Parsing forecast files...")
    # TODO: implement per-model parsers
    # - claude.pdf: most structured (match dates, confidence %, sequential match numbers)
    # - gemini.md: two scenarios per match — score both
    # - chatgpt.md: note group K discrepancy (Portugal vs Jamaica)
    # - doubao.md: includes group standings + best-third-place predictions
    print("Done. Forecasts written to", DB_PATH)


if __name__ == "__main__":
    main()
