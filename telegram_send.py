"""
telegram_send.py — Daily: push the report to a Telegram channel.

Uses python-telegram-bot to send:
  - Formatted leaderboard message
  - Attached HTML report file
  - Accuracy chart image
"""

import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        return

    print("Sending report to Telegram...")
    # TODO: read generated report from reports/
    # TODO: send leaderboard as formatted message
    # TODO: attach HTML report
    # TODO: attach accuracy chart PNG
    print("Report sent.")


if __name__ == "__main__":
    main()
