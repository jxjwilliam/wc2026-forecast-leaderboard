"""
dashboard.py — Minimal FastAPI web dashboard.

Serves generated HTML reports and knockout bracket pages
from the reports/ directory with a date-indexed landing page.

Usage:
    python3 dashboard.py
    # → http://127.0.0.1:8080
"""

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

HOST = "127.0.0.1"
PORT = 8080
REPORT_DIR = Path(__file__).parent / "reports"

app = FastAPI(title="WC2026 Forecast Tracker")

# Mount reports/ as static files at /reports/
REPORT_DIR.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORT_DIR)), name="reports")


def _list_reports() -> list[dict]:
    """Return sorted list of report files with metadata."""
    reports = []
    for f in sorted(REPORT_DIR.iterdir(), reverse=True):
        if f.suffix == ".html":
            is_knockout = f.name.startswith("knockout-")
            label = f.name.replace("knockout-", "").replace(".html", "")
            reports.append({
                "filename": f.name,
                "label": label,
                "is_knockout": is_knockout,
                "size": f.stat().st_size,
            })
    return reports


@app.get("/", response_class=HTMLResponse)
def index():
    reports = _list_reports()
    # Separate regular and knockout reports
    regular = [r for r in reports if not r["is_knockout"]]
    knockouts = [r for r in reports if r["is_knockout"]]

    regular_rows = "".join(
        f'<tr><td><a href="/reports/{r["filename"]}">{r["label"]}</a></td>'
        f'<td>{r["size"]:,} bytes</td></tr>\n'
        for r in regular
    )
    ko_rows = "".join(
        f'<tr><td><a href="/reports/{r["filename"]}">{r["label"]}</a></td>'
        f'<td>{r["size"]:,} bytes</td></tr>\n'
        for r in knockouts
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WC2026 Forecast Tracker — Dashboard</title>
<style>
  body {{ font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
         max-width: 800px; margin: 0 auto; padding: 20px;
         background: #f5f7fa; color: #333; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 8px; }}
  h2 {{ color: #1a1a2e; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0;
           background: #fff; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  th {{ background: #1a1a2e; color: #fff; padding: 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f0f4ff; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .empty {{ color: #888; font-style: italic; padding: 20px; text-align: center; }}
  .nav {{ margin: 16px 0; }}
  .nav a {{ display: inline-block; margin-right: 12px; padding: 6px 14px;
             background: #1a1a2e; color: #fff; border-radius: 6px;
             font-size: 0.9em; }}
  footer {{ margin-top: 30px; font-size: 0.8em; color: #888; text-align: center; }}
</style>
</head>
<body>
<h1>⚽ WC2026 Forecast Tracker</h1>

<div class="nav">
  <a href="/latest">📊 Latest Report</a>
  <a href="/knockout">🏆 Latest Knockout</a>
</div>

<h2>📊 Daily Reports</h2>
<table>
<tr><th>Date</th><th>Size</th></tr>
{regular_rows if regular else '<tr><td class="empty" colspan="2">No reports yet.</td></tr>'}
</table>

<h2>🏆 Knockout Predictions</h2>
<table>
<tr><th>Date</th><th>Size</th></tr>
{ko_rows if knockouts else '<tr><td class="empty" colspan="2">No knockout predictions yet.</td></tr>'}
</table>

<footer>WC2026 Forecast Tracker · Generated daily</footer>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/latest")
def latest():
    """Redirect to the most recent daily report."""
    reports = [r for r in _list_reports() if not r["is_knockout"]]
    if not reports:
        raise HTTPException(status_code=404, detail="No reports found")
    return RedirectResponse(url=f"/reports/{reports[0]['filename']}")


@app.get("/knockout")
def knockout():
    """Redirect to the most recent knockout prediction."""
    reports = [r for r in _list_reports() if r["is_knockout"]]
    if not reports:
        raise HTTPException(status_code=404, detail="No knockout predictions found")
    return RedirectResponse(url=f"/reports/{reports[0]['filename']}")


def main() -> None:
    import uvicorn
    print(f"Dashboard: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
