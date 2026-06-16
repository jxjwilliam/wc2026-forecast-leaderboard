"""
history_chart.py — Daily: generate a multi-model score history chart.

Plots each model's average score per match date as a line chart,
showing how model performance trends over time.
"""

import sqlite3
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

DB_PATH = "forecasts.db"
REPORT_DIR = Path("reports")
CJK_FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
CJK_FONT = fm.FontProperties(fname=CJK_FONT_PATH)

# Colors matching report.py palette
MODEL_COLORS = {
    "ChatGPT": "#4C78A8",
    "Claude": "#F58518",
    "Gemini-1": "#54A24B",
    "Gemini-2": "#E45756",
    "Doubao": "#72B7B2",
    "DeepSeek": "#B279A2",
}


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # Query: avg score per model per match date
    rows = conn.execute("""
        SELECT m2.match_date, m.display_name, ROUND(AVG(s.total), 4) AS avg_score
        FROM scores s
        JOIN predictions p ON p.id = s.prediction_id
        JOIN matches m2 ON m2.id = p.match_id
        JOIN models m ON m.id = p.model_id
        GROUP BY m2.match_date, m.display_name
        ORDER BY m2.match_date, m.display_name
    """).fetchall()

    conn.close()

    if not rows:
        print("[history] No score data to chart.")
        return

    # Organize: {model_name: [(date, avg_score), ...]}
    model_data: dict[str, list[tuple[str, float]]] = {}
    for match_date, model_name, avg_score in rows:
        model_data.setdefault(model_name, []).append((match_date, avg_score))

    # Sort each model's data by date
    for model in model_data:
        model_data[model].sort(key=lambda x: x[0])

    # Build the chart
    fig, ax = plt.subplots(figsize=(10, 5))

    for model, points in model_data.items():
        dates = [mdates.date2num(__parse_date(d)) for d, _ in points]
        scores = [s for _, s in points]
        color = MODEL_COLORS.get(model, "#333333")
        label = model
        if len(points) > 1:
            ax.plot(dates, scores, marker="o", label=label, color=color, linewidth=2, markersize=5)
        else:
            ax.scatter(dates, scores, marker="o", label=label, color=color, s=60, zorder=5)

    ax.set_xlabel("Match Date", fontproperties=CJK_FONT, fontsize=11)
    ax.set_ylabel("Average Score per Match", fontproperties=CJK_FONT, fontsize=11)
    ax.set_title("WC2026 — Model Score History", fontproperties=CJK_FONT, fontsize=14, fontweight="bold")

    # Date axis formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    fig.autofmt_xdate()

    ax.legend(prop=fm.FontProperties(fname=CJK_FONT_PATH, size=9), loc="best")
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Y-axis: start from 0
    y_min = 0
    y_max = max((s for _, points in model_data.items() for _, s in points), default=3.0)
    ax.set_ylim(y_min, y_max * 1.15 + 0.1)

    out_path = REPORT_DIR / "history.png"
    plt.tight_layout()
    plt.savefig(out_path, format="png", dpi=150)
    plt.close(fig)
    print(f"[history] Chart saved: {out_path}")


def __parse_date(d: str) -> date:
    """Parse '2026-06-16' → date object."""
    from datetime import datetime
    return datetime.strptime(d, "%Y-%m-%d").date()


if __name__ == "__main__":
    main()
