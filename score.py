"""
score.py — Daily: compare forecasts against real results and update scores.

Scoring tiers (per model per match):
  - Exact score: 3 pts
  - Correct result (W/D/L): 1 pt
  - Goal difference within 1: +0.5 bonus

Special handling:
  - Gemini: score both Scenario 1 and Scenario 2, take best-of-two
  - Claude PDF: confidence % weighted as multiplier (on result tier, not exact)
"""

import sqlite3

DB_PATH = "forecasts.db"


def main() -> None:
    print("Scoring forecasts against results...")
    # TODO: read results from forecasts.db
    # TODO: for each model prediction, compute tier-based score
    # TODO: handle Gemini dual-scenario scoring
    # TODO: handle Claude confidence weighting
    # TODO: update scores table
    print("Scoring complete.")


if __name__ == "__main__":
    main()
