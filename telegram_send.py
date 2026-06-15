"""
telegram_send.py — Daily: push the report to a Telegram channel.

Uses python-telegram-bot to send:
  - Formatted leaderboard message
  - Attached HTML report file
"""

import asyncio
import os
import sqlite3
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DB_PATH = "forecasts.db"
REPORT_DIR = Path("reports")


def _build_leaderboard_text() -> str:
    """Build a compact leaderboard text from scores."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT m.display_name,
               COUNT(*)                            AS n,
               ROUND(AVG(s.total), 4)              AS avg_total,
               ROUND(SUM(s.total), 2)              AS sum_total,
               ROUND(AVG(CASE WHEN s.total > 0 THEN 1 ELSE 0 END) * 100, 1) AS acc
        FROM scores s
        JOIN predictions p ON p.id = s.prediction_id
        JOIN models      m ON m.id = p.model_id
        JOIN results     r ON r.match_id = p.match_id
        GROUP BY m.id
        ORDER BY avg_total DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "📊 <b>WC2026 Forecast Tracker</b>\nNo scores yet."

    lines = [
        "📊 <b>WC2026 Forecast Tracker — {}</b>\n".format(date.today()),
        "<pre>{:<10} {:>6} {:>6} {:>6} {:>5}</pre>".format(
            "Model", "Avg", "Total", "Pts%", "N"
        ),
        "<pre>" + "-" * 35 + "</pre>",
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, n, avg, total, acc) in enumerate(rows):
        prefix = medals[i] if i < 3 else f"  {i+1}."
        lines.append(
            f"<pre>{prefix} {name:<8} {avg:>5.3f} {total:>6.2f} {acc:>5.1f}% {n:>3}</pre>"
        )
    return "\n".join(lines)


async def _send() -> None:
    """Async: send leaderboard + HTML report to Telegram."""
    bot = Bot(token=BOT_TOKEN)

    # 1. Leaderboard text
    text = _build_leaderboard_text()
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text,
                               parse_mode="HTML")
        print("  Leaderboard sent.")
    except TelegramError as e:
        print(f"  ERROR sending leaderboard: {e}")

    # 2. Attach HTML report
    report_path = REPORT_DIR / f"{date.today()}.html"
    if report_path.exists():
        try:
            with open(report_path, "rb") as f:
                await bot.send_document(chat_id=CHAT_ID, document=f,
                                        filename=report_path.name)
            print(f"  Report file sent: {report_path.name}")
        except TelegramError as e:
            print(f"  ERROR sending report file: {e}")
    else:
        print(f"  SKIP: no report file at {report_path}")


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        return

    print("Sending report to Telegram...")
    asyncio.run(_send())
    print("Done.")


if __name__ == "__main__":
    main()
