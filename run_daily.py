"""
run_daily.py — Orchestrator: runs the full daily pipeline.

Sequences: fetch_results -> score -> report -> telegram_send
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on the path  
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

from fetch_results import main as fetch_main  # noqa: E402
from score import main as score_main          # noqa: E402
from knockout import main as knockout_main    # noqa: E402
from report import main as report_main        # noqa: E402
from telegram_send import main as telegram_main  # noqa: E402


def main() -> None:
    print("=== WC2026 Forecast Tracker — Daily Run ===")

    fetch_main()
    score_main()

    knockout_result = knockout_main()
    if knockout_result:
        print(f"[pipeline] Knockout summary:\n{knockout_result}")

    report_main()
    telegram_main()

    print("=== Daily run complete ===")


if __name__ == "__main__":
    main()
