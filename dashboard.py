"""
dashboard.py — FastAPI web dashboard with chat, notifications, and Telegram.

Endpoints:
  GET  /              — Index page with reports list + notifications
  GET  /latest        — Redirect to most recent report
  GET  /knockout      — Redirect to most recent knockout page
  GET  /chat          — NL→SQL chat interface
  POST /api/chat      — Accept NL question, return query results
  POST /api/telegram  — Trigger Telegram send of latest report
  Static /reports/*   — Reports directory files

Usage:
    python3 dashboard.py
    # → http://127.0.0.1:8080
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import requests

load_dotenv()

HOST = "127.0.0.1"
PORT = 8080
DB_PATH = "forecasts.db"
REPORT_DIR = Path(__file__).parent / "reports"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

app = FastAPI(title="WC2026 Forecast Tracker")
REPORT_DIR.mkdir(exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORT_DIR)), name="reports")

# ─── Database helpers ─────────────────────────────────────────────────────────

DB_SCHEMA_PROMPT = """
Database: forecasts.db (SQLite)
Tables:
- models(id INTEGER PK, name TEXT UNIQUE, display_name TEXT, source_file TEXT)
  Example: (1, "chatgpt", "ChatGPT", "chatgpt.md")
- matches(id INTEGER PK, match_number INTEGER, group_name TEXT, round INTEGER, home_team TEXT, away_team TEXT, match_date TEXT, stage TEXT)
  Example: (1, 1, "A", 1, "墨西哥", "南非", "2026-06-11", "group")
  - group_name: A-L, stage: 'group'
  - home_team and away_team are Chinese team names
- predictions(id INTEGER PK, model_id INTEGER FK, match_id INTEGER FK, scenario TEXT, home_score INTEGER, away_score INTEGER, confidence REAL)
  - scenario: 'single' or 'scenario_1'/'scenario_2' (for Gemini)
- results(id INTEGER PK, match_id INTEGER UNIQUE FK, home_score INTEGER, away_score INTEGER, fetched_at TEXT)
- scores(id INTEGER PK, prediction_id INTEGER UNIQUE FK, exact_score INTEGER (0 or 3 points), correct_result REAL (0-1 points), goal_diff_bonus REAL (0-0.5), total REAL)

Useful joins:
- scores → predictions ON scores.prediction_id = predictions.id
- predictions → matches ON predictions.match_id = matches.id
- predictions → models ON predictions.model_id = models.id
- results → matches ON results.match_id = matches.id

Rules:
- Return ONLY the SQL query, no markdown fences, no explanation.
- Use display_name for model names.
- Team names are Chinese (e.g., 墨西哥, 美国, 巴西, 德国, 法国, 英格兰).
- exact_score is 3 when the prediction matches the exact result, otherwise 0. Use WHERE exact_score > 0 to find exact matches.
- correct_result is 1 (or less if Claude confidence-adjusted) when result direction is correct but not exact, otherwise 0.
- goal_diff_bonus is 0.5 when goal difference is within 1, otherwise 0.
- Group names are single letters A-L.
- Total matches in group stage: 72.
- 6 models: ChatGPT, Claude, Gemini-1, Gemini-2, Doubao, DeepSeek.
- Gemini has two scenarios: model names 'gemini1'/'gemini2' in name column.
"""


def _get_db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _execute_safe(sql: str) -> dict:
    """Execute a SELECT query safely. Return {columns, rows, error}."""
    sql_stripped = sql.strip().rstrip(";")

    # Only allow SELECT
    if not re.match(r"^\s*SELECT\s", sql_stripped, re.IGNORECASE):
        return {"columns": [], "rows": [], "error": "Only SELECT queries are allowed."}

    # Block dangerous statements
    for keyword in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "PRAGMA", "ATTACH"):
        if re.search(rf"\b{keyword}\b", sql_stripped, re.IGNORECASE):
            return {"columns": [], "rows": [], "error": f"Keyword '{keyword}' is not allowed."}

    try:
        conn = _get_db_conn()
        cur = conn.execute(sql_stripped)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = [list(row) for row in cur.fetchall()]
        conn.close()
        return {"columns": columns, "rows": rows, "error": None}
    except Exception as e:
        return {"columns": [], "rows": [], "error": str(e)}


def _call_deepseek(question: str) -> str | None:
    """Send a question to DeepSeek and return the SQL response."""
    if not DEEPSEEK_API_KEY:
        return None

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DB_SCHEMA_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": 500,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        content = re.sub(r"^```(?:sql)?\s*", "", content, flags=re.IGNORECASE)
        content = content.rstrip("`").strip()
        return content
    except Exception as e:
        print(f"[chat] DeepSeek error: {e}")
        return None


# ─── Notifications ────────────────────────────────────────────────────────────

def _get_notifications() -> list[dict]:
    """Return a list of notification dicts for the dashboard index."""
    notes: list[dict] = []
    try:
        conn = _get_db_conn()

        # Today's matches
        today_rows = conn.execute("""
            SELECT m.id, m.group_name, m.home_team, m.away_team, m.match_date,
                   r.home_score IS NOT NULL AS has_result,
                   r.home_score, r.away_score
            FROM matches m
            LEFT JOIN results r ON r.match_id = m.id
            WHERE m.match_date = ?
            ORDER BY m.match_number
        """, (date.today().isoformat(),)).fetchall()

        if today_rows:
            match_lines = []
            for r in today_rows:
                if r["has_result"]:
                    match_lines.append(
                        f"{r['home_team']} {r['home_score']}-{r['away_score']} {r['away_team']} ✅"
                    )
                else:
                    match_lines.append(f"{r['home_team']} vs {r['away_team']} ⏳")
            notes.append({
                "type": "info",
                "icon": "🗓",
                "title": f"Today's Matches ({len(today_rows)})",
                "lines": match_lines,
            })

        # Overdue results (matches past today with no result)
        overdue = conn.execute("""
            SELECT m.match_date, m.group_name, m.home_team, m.away_team
            FROM matches m
            LEFT JOIN results r ON r.match_id = m.id
            WHERE m.match_date < ? AND r.id IS NULL
            ORDER BY m.match_date
        """, (date.today().isoformat(),)).fetchall()

        if overdue:
            lines = [f"{r['match_date']} — {r['group_name']}: {r['home_team']} vs {r['away_team']}"
                     for r in overdue]
            notes.append({
                "type": "warning",
                "icon": "⏳",
                "title": f"Overdue Results ({len(overdue)})",
                "lines": lines,
            })

        # Leader model
        leader = conn.execute("""
            SELECT m.display_name, ROUND(AVG(s.total), 4) AS avg_score, COUNT(*) AS n
            FROM scores s
            JOIN predictions p ON p.id = s.prediction_id
            JOIN models m ON m.id = p.model_id
            GROUP BY m.id
            ORDER BY avg_score DESC
            LIMIT 1
        """).fetchone()

        if leader:
            notes.append({
                "type": "info",
                "icon": "🏆",
                "title": "Current Leader",
                "lines": [f"{leader['display_name']} — {leader['avg_score']:.4f} avg ({leader['n']} matches)"],
            })

        # Progress
        total_matches = conn.execute("SELECT COUNT(*) FROM matches WHERE stage='group'").fetchone()[0]
        scored_matches = conn.execute("SELECT COUNT(DISTINCT match_id) FROM results").fetchone()[0]
        pct = round(scored_matches / total_matches * 100, 1) if total_matches else 0
        notes.append({
            "type": "info",
            "icon": "📊",
            "title": "Tournament Progress",
            "lines": [f"{scored_matches}/{total_matches} group matches played ({pct}%)"],
        })

        # Missing predictions (models without predictions for matches that have results)
        missing = conn.execute("""
            SELECT m.display_name, COUNT(*) AS missing_count
            FROM results r
            JOIN matches m2 ON m2.id = r.match_id
            CROSS JOIN models m
            WHERE NOT EXISTS (
                SELECT 1 FROM predictions p
                WHERE p.model_id = m.id AND p.match_id = r.match_id
            )
            GROUP BY m.display_name
            HAVING missing_count > 0
            ORDER BY missing_count DESC
        """).fetchall()

        if missing:
            lines = [f"{r['display_name']}: {r['missing_count']} missing predictions" for r in missing]
            notes.append({
                "type": "warning",
                "icon": "⚠️",
                "title": "Missing Predictions",
                "lines": lines,
            })

        conn.close()
    except Exception as e:
        notes.append({
            "type": "error",
            "icon": "🔴",
            "title": "Dashboard Error",
            "lines": [str(e)],
        })

    if not notes:
        notes.append({
            "type": "info",
            "icon": "✅",
            "title": "All Clear",
            "lines": ["No issues detected."],
        })

    return notes


# ─── Endpoints ────────────────────────────────────────────────────────────────

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
    regular = [r for r in reports if not r["is_knockout"]]
    knockouts = [r for r in reports if r["is_knockout"]]
    notifications = _get_notifications()

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

    # Notifications HTML
    notes_html = ""
    for n in notifications:
        type_class = n["type"]  # info, warning, error
        lines_html = "".join(f"<div>{line}</div>" for line in n["lines"])
        notes_html += f"""<div class="note note-{type_class}">
  <div class="note-title">{n["icon"]} {n["title"]}</div>
  <div class="note-body">{lines_html}</div>
</div>
"""

    # History chart (if exists)
    history_img = ""
    if (REPORT_DIR / "history.png").exists():
        history_img = f"""
<h2>📈 Score History</h2>
<div class="chart">
  <img src="/reports/history.png" alt="Model score history">
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WC2026 Forecast Tracker — Dashboard</title>
<style>
  body {{ font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
         max-width: 900px; margin: 0 auto; padding: 20px;
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
  .nav {{ margin: 16px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
  .nav a, .nav button {{
    display: inline-block; padding: 8px 16px;
    background: #1a1a2e; color: #fff; border-radius: 6px;
    font-size: 0.9em; border: none; cursor: pointer;
    text-decoration: none; font-family: inherit;
  }}
  .nav button:hover {{ opacity: 0.9; }}
  footer {{ margin-top: 30px; font-size: 0.8em; color: #888; text-align: center; }}
  .chart {{ text-align: center; margin: 20px 0; }}
  .chart img {{ max-width: 100%; height: auto; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  /* Notifications */
  .notifications {{ margin: 16px 0; }}
  .note {{ padding: 12px 16px; margin: 8px 0; border-radius: 8px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .note-info {{ background: #e8f4fd; border-left: 4px solid #2196f3; }}
  .note-warning {{ background: #fff3e0; border-left: 4px solid #ff9800; }}
  .note-error {{ background: #fde8e8; border-left: 4px solid #f44336; }}
  .note-title {{ font-weight: bold; margin-bottom: 4px; font-size: 1.05em; }}
  .note-body {{ font-size: 0.9em; color: #555; }}
  .note-body div {{ padding: 2px 0; }}
  /* Toast */
  .toast {{ position: fixed; bottom: 20px; right: 20px; padding: 12px 20px;
             border-radius: 8px; color: #fff; font-size: 0.9em;
             opacity: 0; transition: opacity 0.3s; z-index: 999; }}
  .toast.show {{ opacity: 1; }}
  .toast-success {{ background: #4caf50; }}
  .toast-error {{ background: #f44336; }}
</style>
</head>
<body>
<h1>⚽ WC2026 Forecast Tracker</h1>

<div class="nav">
  <a href="/latest">📊 Latest Report</a>
  <a href="/knockout">🏆 Latest Knockout</a>
  <a href="/chat">💬 Chat with Data</a>
  <button onclick="sendTelegram()">📤 Send to Telegram</button>
</div>

<div class="notifications">
  {notes_html}
</div>

{history_img}

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

<div id="toast" class="toast"></div>

<footer>WC2026 Forecast Tracker · {date.today()}</footer>

<script>
async function sendTelegram() {{
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Sending...';
  try {{
    const resp = await fetch('/api/telegram', {{ method: 'POST' }});
    const data = await resp.json();
    showToast(data.status === 'ok' ? '✅ Sent to Telegram!' : '❌ ' + data.message,
              data.status === 'ok' ? 'success' : 'error');
  }} catch(e) {{
    showToast('❌ Network error', 'error');
  }}
  btn.disabled = false;
  btn.textContent = '📤 Send to Telegram';
}}

function showToast(msg, type) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 4000);
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/latest")
def latest():
    reports = [r for r in _list_reports() if not r["is_knockout"]]
    if not reports:
        raise HTTPException(status_code=404, detail="No reports found")
    return RedirectResponse(url=f"/reports/{reports[0]['filename']}")


@app.get("/knockout")
def knockout():
    reports = [r for r in _list_reports() if r["is_knockout"]]
    if not reports:
        raise HTTPException(status_code=404, detail="No knockout predictions found")
    return RedirectResponse(url=f"/reports/{reports[0]['filename']}")


# ─── Chat ─────────────────────────────────────────────────────────────────────

CHAT_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WC2026 — Chat with Data</title>
<style>
  body { font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
         max-width: 900px; margin: 0 auto; padding: 20px;
         background: #f5f7fa; color: #333; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 8px; }
  .nav { margin: 16px 0; }
  .nav a { display: inline-block; padding: 6px 14px; background: #1a1a2e;
            color: #fff; border-radius: 6px; text-decoration: none; font-size: 0.9em; }
  #chat-box { background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08);
              padding: 16px; height: 400px; overflow-y: auto; margin: 12px 0; }
  .msg { margin: 8px 0; padding: 10px 14px; border-radius: 8px; max-width: 85%;
         line-height: 1.4; font-size: 0.95em; }
  .user-msg { background: #e3f2fd; margin-left: auto; text-align: right; }
  .bot-msg { background: #f5f5f5; margin-right: auto; }
  .bot-msg table { width: 100%; border-collapse: collapse; margin: 8px 0;
                    font-size: 0.88em; }
  .bot-msg th { background: #1a1a2e; color: #fff; padding: 6px; text-align: left; }
  .bot-msg td { padding: 5px 6px; border-bottom: 1px solid #eee; }
  .bot-msg tr:nth-child(even) td { background: #fafafa; }
  .bot-msg .sql-block { background: #272822; color: #f8f8f2; padding: 8px 12px;
                         border-radius: 4px; font-family: 'SF Mono', monospace;
                         font-size: 0.8em; margin: 6px 0; overflow-x: auto;
                         cursor: pointer; }
  .bot-msg .sql-label { font-size: 0.78em; color: #888; margin-top: 4px; }
  .bot-msg .error { color: #d32f2f; font-weight: 500; }
  .bot-msg .empty { color: #888; font-style: italic; }
  .input-row { display: flex; gap: 8px; }
  .input-row input { flex: 1; padding: 10px 14px; border: 1px solid #ddd;
                      border-radius: 8px; font-size: 0.95em; outline: none; }
  .input-row input:focus { border-color: #1a73e8; }
  .input-row button { padding: 10px 20px; background: #1a73e8; color: #fff;
                       border: none; border-radius: 8px; cursor: pointer;
                       font-size: 0.95em; }
  .input-row button:disabled { opacity: 0.6; cursor: not-allowed; }
  .typing { color: #888; font-style: italic; font-size: 0.85em; padding: 8px; }
  .suggestions { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
  .suggestions button { padding: 6px 12px; background: #e8eaf6; border: 1px solid #c5cae9;
                         border-radius: 16px; cursor: pointer; font-size: 0.82em;
                         color: #283593; }
  .suggestions button:hover { background: #c5cae9; }
  details { margin: 4px 0; }
  summary { font-size: 0.82em; color: #666; cursor: pointer; }
</style>
</head>
<body>
<h1>💬 Chat with Data</h1>
<div class="nav"><a href="/">← Back to Dashboard</a></div>
<p style="color:#666;font-size:0.9em;">Ask questions about the forecasts in natural language. Powered by DeepSeek AI.</p>

<div id="chat-box">
  <div class="msg bot-msg">
    <strong>🤖 Hello!</strong> Ask me anything about the WC2026 forecast data. For example:
    <div class="suggestions">
      <button onclick="ask('Which model has the highest average score?')">Which model has the highest average score?</button>
      <button onclick="ask('Show me all matches in Group A')">Show me all matches in Group A</button>
      <button onclick="ask('Which match has the most exact score predictions?')">Which match has the most exact score predictions?</button>
    </div>
  </div>
</div>

<div class="input-row">
  <input type="text" id="question-input" placeholder="Ask a question about the data..."
         onkeydown="if(event.key==='Enter') send()">
  <button id="send-btn" onclick="send()">Ask</button>
</div>

<script>
async function send() {
  const input = document.getElementById('question-input');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  ask(q);
}

async function ask(question) {
  const box = document.getElementById('chat-box');
  const btn = document.getElementById('send-btn');

  // User message
  box.innerHTML += `<div class="msg user-msg">${escapeHtml(question)}</div>`;
  box.scrollTop = box.scrollHeight;

  // Typing indicator
  const typingDiv = document.createElement('div');
  typingDiv.className = 'typing';
  typingDiv.textContent = '🤖 Thinking...';
  box.appendChild(typingDiv);
  box.scrollTop = box.scrollHeight;

  btn.disabled = true;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question})
    });
    const data = await resp.json();
    typingDiv.remove();

    let html = '<div class="msg bot-msg">';

    if (data.error) {
      html += `<div class="error">❌ ${escapeHtml(data.error)}</div>`;
      if (data.sql) {
        html += `<details><summary>View SQL</summary><div class="sql-block">${escapeHtml(data.sql)}</div></details>`;
      }
    } else if (data.columns && data.columns.length > 0) {
      // Build table
      html += '<table><tr>';
      data.columns.forEach(c => { html += `<th>${escapeHtml(c)}</th>`; });
      html += '</tr>';
      data.rows.forEach(r => {
        html += '<tr>';
        r.forEach(v => { html += `<td>${escapeHtml(v != null ? String(v) : 'NULL')}</td>`; });
        html += '</tr>';
      });
      html += `</table><div style="font-size:0.82em;color:#888;">${data.rows.length} row(s)</div>`;
      html += `<details><summary>View SQL</summary><div class="sql-block">${escapeHtml(data.sql)}</div></details>`;
    } else {
      html += '<div class="empty">No results found for your query.</div>';
    }

    html += '</div>';
    box.innerHTML += html;

  } catch(e) {
    typingDiv.remove();
    box.innerHTML += `<div class="msg bot-msg"><div class="error">❌ Network error: ${escapeHtml(e.message)}</div></div>`;
  }

  box.scrollTop = box.scrollHeight;
  btn.disabled = false;
}

function escapeHtml(text) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(text));
  return d.innerHTML;
}
</script>
</body>
</html>
"""


@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    return HTMLResponse(content=CHAT_HTML)


@app.post("/api/chat")
async def api_chat(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"sql": None, "columns": [], "rows": [], "error": "Empty question."})

    sql = _call_deepseek(question)
    if sql is None:
        return JSONResponse({"sql": None, "columns": [], "rows": [],
                             "error": "Sorry, the AI query service is unavailable. Check DEEPSEEK_API_KEY."})

    result = _execute_safe(sql)
    result["sql"] = sql
    return JSONResponse(result)


# ─── Telegram send ────────────────────────────────────────────────────────────

@app.post("/api/telegram")
async def api_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return JSONResponse({"status": "error", "message": "Telegram not configured."})

    try:
        # Run telegram_send.main() in a subprocess to avoid import issues
        result = subprocess.run(
            [sys.executable, "-c", """
from dotenv import load_dotenv
load_dotenv()
from telegram_send import main
main()
"""],
            capture_output=True, text=True, timeout=60,
            cwd=Path(__file__).parent,
        )
        if result.returncode == 0:
            return JSONResponse({"status": "ok", "message": "Sent successfully."})
        else:
            return JSONResponse({"status": "error", "message": result.stderr.strip() or "Unknown error."})
    except subprocess.TimeoutExpired:
        return JSONResponse({"status": "error", "message": "Telegram send timed out."})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import uvicorn
    print(f"Dashboard: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
