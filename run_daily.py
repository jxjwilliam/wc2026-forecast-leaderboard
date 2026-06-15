"""
run_daily.py — Orchestrator: runs the full daily pipeline.

Sequences: fetch_results -> score -> report -> telegram_send
"""

import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

import fetch_results
import score
import report
import telegram_send


def main() -> None:
    print("=== WC2026 Forecast Tracker — Daily Run ===")

    fetch_results.main()
    score.main()
    report.main()
    telegram_send.main()

    print("=== Daily run complete ===")


if __name__ == "__main__":
    main()
