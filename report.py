"""
report.py — Daily: generate a self-contained HTML report with charts.

Report sections:
   1. Leaderboard (ranked table)
   2. Running accuracy chart (matplotlib PNG embedded in HTML)
   3. Today's Match Forecasts (if matches scheduled today)
   4. Match comparison (prediction vs real result per model)
"""

import base64
import io
import sqlite3
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

DB_PATH = "forecasts.db"
REPORT_DIR = Path("reports")
# macOS Chinese font for matplotlib
CJK_FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
CJK_FONT = fm.FontProperties(fname=CJK_FONT_PATH)

# Model display order for today's forecast table
MODEL_ORDER = ["ChatGPT", "Claude", "Gemini-1", "Gemini-2", "Doubao", "DeepSeek"]


def _fmt_team(name: str) -> str:
    """Shorten overlength team names for the HTML table."""
    if len(name) > 8:
        return name[:8] + "…"
    return name


def _build_leaderboard(cur: sqlite3.Cursor) -> list[dict]:
    """Return per-model aggregate scores ordered by avg descending."""
    cur.execute("""
        SELECT m.display_name,
               COUNT(*)                            AS n,
               SUM(s.exact_score)                  AS exact_pts,
               SUM(s.correct_result)               AS result_pts,
               SUM(s.goal_diff_bonus)              AS bonus_pts,
               ROUND(AVG(s.total), 4)              AS avg_total,
               ROUND(SUM(s.total), 2)              AS sum_total,
               ROUND(AVG(CASE WHEN s.total > 0 THEN 1 ELSE 0 END) * 100, 1) AS accuracy_pct
        FROM scores s
        JOIN predictions p ON p.id = s.prediction_id
        JOIN models      m ON m.id = p.model_id
        JOIN results     r ON r.match_id = p.match_id
        GROUP BY m.id
        ORDER BY avg_total DESC
    """)
    return [
        {
            "name": row[0],
            "matches": row[1],
            "exact_pts": row[2],
            "result_pts": round(row[3], 4),
            "bonus_pts": round(row[4], 4),
            "avg_total": row[5],
            "sum_total": row[6],
            "accuracy_pct": row[7],
        }
        for row in cur.fetchall()
    ]


def _build_match_rows(cur: sqlite3.Cursor) -> list[dict]:
    """Return each match with all model predictions and actual score."""
    cur.execute("""
        SELECT r.id, r.match_id, m2.home_team, m2.away_team,
               r.home_score, r.away_score,
               m.display_name, p.home_score, p.away_score, s.total
        FROM results r
        JOIN matches m2 ON m2.id = r.match_id
        LEFT JOIN predictions p ON p.match_id = r.match_id
        LEFT JOIN models m ON m.id = p.model_id
        LEFT JOIN scores s ON s.prediction_id = p.id
        ORDER BY r.match_id, m.id
    """)
    rows = cur.fetchall()
    matches: dict[int, dict] = {}
    for row in rows:
        mid = row[1]
        if mid not in matches:
            matches[mid] = {
                "home": row[2],
                "away": row[3],
                "home_score": row[4],
                "away_score": row[5],
                "predictions": [],
            }
        if row[6] is not None:
            matches[mid]["predictions"].append({
                "model": row[6],
                "pred_h": row[7],
                "pred_a": row[8],
                "score": row[9],
            })
    return list(matches.values())


def _build_todays_forecasts(cur: sqlite3.Cursor, today: date) -> list[dict]:
    """Return today's matches with all model predictions and actual result."""
    cur.execute("""
        SELECT mt.group_name, mt.home_team, mt.away_team, mt.match_number,
               m.display_name, p.home_score, p.away_score, p.scenario,
               r.home_score AS actual_h, r.away_score AS actual_a
        FROM matches mt
        JOIN predictions p ON p.match_id = mt.id
        JOIN models m ON m.id = p.model_id
        LEFT JOIN results r ON r.match_id = mt.id
        WHERE mt.match_date = ?
        ORDER BY mt.match_number, m.id, p.scenario
    """, (today.isoformat(),))
    rows = cur.fetchall()

    if not rows:
        return []

    matches: dict[int, dict] = {}
    for row in rows:
        group, home, away, match_num, model_name, pred_h, pred_a, scenario, act_h, act_a = row
        if match_num not in matches:
            matches[match_num] = {
                "group": group,
                "home": home,
                "away": away,
                "actual_h": act_h,
                "actual_a": act_a,
                "preds": {m: [] for m in MODEL_ORDER},
            }
        pred_str = f"{pred_h}-{pred_a}"
        matches[match_num]["preds"].setdefault(model_name, []).append(pred_str)

    result = []
    for match_num in sorted(matches.keys()):
        m = matches[match_num]
        pred_cells = []
        for model in MODEL_ORDER:
            scores = m["preds"].get(model, [])
            if not scores:
                pred_cells.append("—")
            else:
                pred_cells.append(" / ".join(scores))
        result.append({
            "group": m["group"],
            "home": m["home"],
            "away": m["away"],
            "actual_h": m["actual_h"],
            "actual_a": m["actual_a"],
            "preds": pred_cells,
        })

    return result


def _generate_chart(leaderboard: list[dict]) -> str:
    """Generate a matplotlib bar chart, return base64 PNG."""
    labels = [r["name"] for r in leaderboard]
    avg_scores = [r["avg_total"] for r in leaderboard]
    match_counts = [r["matches"] for r in leaderboard]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756"]
    bars = ax.bar(labels, avg_scores, color=colors[:len(labels)], edgecolor="white", width=0.55)

    for i, (bar, mc) in enumerate(zip(bars, match_counts)):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{avg_scores[i]:.3f}", ha="center", va="bottom",
                fontsize=11, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, 0.02,
                f"n={mc}", ha="center", va="bottom",
                fontsize=9, color="white", fontweight="bold")

    ax.set_ylabel("Avg Score per Match", fontproperties=CJK_FONT, fontsize=12)
    ax.set_title("WC2026 Forecast Tracker — Model Ranking",
                 fontproperties=CJK_FONT, fontsize=14, fontweight="bold")
    ax.set_ylim(0, max(avg_scores) * 1.25 + 0.1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", labelsize=11)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _generate_html(leaderboard: list[dict], match_rows: list[dict],
                   chart_b64: str, today: date,
                   todays_forecasts: list[dict] | None = None) -> str:
    """Build a self-contained HTML page."""
    rows_html = ""
    for i, r in enumerate(leaderboard):
        rank_icon = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}"
        rows_html += f"""<tr>
          <td>{rank_icon}</td>
          <td><strong>{r['name']}</strong></td>
          <td>{r['matches']}</td>
          <td>{r['exact_pts']}</td>
          <td>{r['result_pts']}</td>
          <td>{r['bonus_pts']}</td>
          <td>{r['avg_total']:.3f}</td>
          <td>{r['sum_total']:.2f}</td>
          <td>{r['accuracy_pct']}%</td>
        </tr>\n"""

    todays_html = ""
    if todays_forecasts:
        for m in todays_forecasts:
            actual = (f"{m['actual_h']}-{m['actual_a']}"
                      if m['actual_h'] is not None else "—")
            pred_cells = "".join(
                f"<td>{m['preds'][i]}</td>\n"
                for i in range(len(m['preds']))
            )
            todays_html += f"""<tr>
              <td>{m['group']}</td>
              <td>{_fmt_team(m['home'])}</td>
              <td>{_fmt_team(m['away'])}</td>
              {pred_cells}              <td><strong>{actual}</strong></td>
            </tr>\n"""

    match_html = ""
    for m in match_rows:
        pred_cells = ""
        for p in m["predictions"]:
            match_emoji = ""
            if p["pred_h"] == m["home_score"] and p["pred_a"] == m["away_score"]:
                match_emoji = " ✅"
            elif (p["pred_h"] - p["pred_a"]) * (m["home_score"] - m["away_score"]) > 0:
                match_emoji = " ✓"
            else:
                match_emoji = " ✗"
            score_str = f"{p['score']:.2f}pts" if p['score'] is not None else "—"
            pred_cells += (
                f"<span class='pred {match_emoji.strip()}'>{p['model']}: "
                f"{p['pred_h']}-{p['pred_a']} <small>({score_str})</small>{match_emoji}</span><br>\n"
            )

        match_html += f"""<tr>
          <td>{_fmt_team(m['home'])}</td>
          <td><strong>{m['home_score']}-{m['away_score']}</strong></td>
          <td>{_fmt_team(m['away'])}</td>
          <td>{pred_cells}</td>
        </tr>\n"""

    todays_section = ""
    if todays_forecasts:
        model_headers = "".join(f"<th>{m}</th>\n" for m in MODEL_ORDER)
        todays_section = f"""<h2>🔮 Today's Match Forecasts</h2>
<div class="match-section">
<table>
  <tr><th>Group</th><th>Home</th><th>Away</th>
  {model_headers}  <th>Actual</th></tr>
  {todays_html}
</table>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚽</text></svg>">
<title>WC2026 Forecast Tracker — {today}</title>
<style>
  body {{
    font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
    max-width: 1000px; margin: 0 auto; padding: 20px;
    background: #f5f7fa; color: #333;
  }}
  h1, h2 {{ color: #1a1a2e; }}
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
  .nav a, .nav button {{
    display: inline-block; padding: 7px 14px;
    background: #1a1a2e; color: #fff; border-radius: 6px;
    font-size: 0.85em; border: none; cursor: pointer;
    text-decoration: none; font-family: inherit; white-space: nowrap;
  }}
  .nav a:hover {{ opacity: 0.9; }}
  table {{
    width: 100%; border-collapse: collapse; margin: 16px 0;
    background: #fff; border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }}
  th {{ background: #1a1a2e; color: #fff; padding: 10px 8px; text-align: center; font-size: 0.9em; }}
  td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f0f4ff; }}
  .chart {{ text-align: center; margin: 20px 0; }}
  .chart img {{ max-width: 100%; height: auto; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .pred {{ display: inline-block; margin: 2px 0; font-size: 0.85em; }}
  .pred.✅ {{ color: #1a7a1a; }}
  .pred.✓ {{ color: #d4a017; }}
  .pred.✗ {{ color: #b00; }}
  .match-section {{ overflow-x: auto; }}
  .match-section td {{ vertical-align: top; }}
  footer {{ margin-top: 30px; font-size: 0.8em; color: #888; text-align: center; }}
</style>
</head>
<body>
<div class="header">
  <h1><a href="/" class="logo">⚽ WC2026 Forecast Tracker — {today}</a></h1>
  <div class="nav">
    <a href="/latest">📊 Report</a>
    <a href="/knockout">🏆 Bracket</a>
    <a href="/chat">💬 Chat</a>
  </div>
</div>

<h2>📊 Leaderboard</h2>
<table>
  <tr><th>#</th><th>Model</th><th>Matches</th><th>Exact</th><th>Result</th><th>Bonus</th><th>Avg</th><th>Total</th><th>Accuracy</th></tr>
  {rows_html}
</table>

<div class="chart">
  <img src="data:image/png;base64,{chart_b64}" alt="Model ranking chart">
</div>

{todays_section}
<h2>📋 Match Results vs Predictions</h2>
<div class="match-section">
<table>
  <tr><th>Home</th><th>Score</th><th>Away</th><th>Predictions</th></tr>
  {match_html}
</table>
</div>

<footer>Generated by WC2026 Forecast Tracker · Data from football-data.org</footer>
</body>
</html>"""


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    today = date.today()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    leaderboard = _build_leaderboard(cur)
    match_rows = _build_match_rows(cur)
    todays_forecasts = _build_todays_forecasts(cur, today)
    conn.close()

    if not leaderboard:
        print("No scores to report.")
        return

    chart_b64 = _generate_chart(leaderboard)
    html = _generate_html(leaderboard, match_rows, chart_b64, today, todays_forecasts)

    out_path = REPORT_DIR / f"{today}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Report saved: {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
