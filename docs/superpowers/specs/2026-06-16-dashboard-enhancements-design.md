# Dashboard Enhancements — Design Spec

## Overview

Three additions to the WC2026 Forecast Tracker:

1. **History Chart** — Multi-line matplotlib chart showing each model's average score over time (by match date).
2. **Dashboard Chat** — NL→SQL chat interface using DeepSeek API so users can query data conversationally.
3. **Dashboard UX** — Notifications panel, Telegram send button, and general UI improvements on the index page.

---

## Feature 1: History Chart (`history_chart.py`)

### Data Source

Join `scores → predictions → matches` and group by `match_date` and `model_id`:

```sql
SELECT m2.match_date, m.display_name, AVG(s.total) AS avg_score
FROM scores s
JOIN predictions p ON p.id = s.prediction_id
JOIN matches m2 ON m2.id = p.match_id
JOIN models m ON m.id = p.model_id
GROUP BY m2.match_date, m.display_name
ORDER BY m2.match_date, m.display_name
```

### Output

- `reports/history.png` — multi-line chart, one line per model
- X-axis: match dates (chronological)
- Y-axis: average score per match
- Each model gets a distinct color (same palette as `report.py`)
- Legend identifying each line
- Title: "WC2026 — Model Score History"
- Grid for readability

### Edge Cases

- **Only 1 date** → dot scatter instead of lines (no trend yet)
- **No scores** → skip silently, no file generated
- **Date gaps** → lines connect through missing dates; no interpolation needed

### Integration

Called from `run_daily.py` after scoring, before report generation:
```
fetch_results → score → history_chart → knockdown → report → telegram_send
```

---

## Feature 2: Dashboard Chat (`/chat` page)

### Architecture

```
User types question in browser
  → fetch POST /api/chat {question: "..."}
    → dashboard.py constructs system prompt with DB schema
    → POST to DeepSeek API (chat/completions)
    → Parse DeepSeek response → extract SQL query
    → Execute SQL against forecasts.db
    → Return {sql, columns, rows, error} as JSON
  → Chat UI renders results as a styled table
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/chat` | Serves the chat HTML page |
| POST | `/api/chat` | Accept NL question, return query results |

### POST /api/chat

**Request:** `{"question": "which model has the highest average score?"}`

**Response (success):**
```json
{
  "sql": "SELECT display_name, ROUND(AVG(total),4) ...",
  "columns": ["Model", "Avg Score"],
  "rows": [["Gemini-2", 1.5938], ...],
  "error": null
}
```

**Response (error):**
```json
{
  "sql": null,
  "columns": [],
  "rows": [],
  "error": "DeepSeek returned invalid SQL: ..."
}
```

### DeepSeek System Prompt

The system prompt includes:
- Full table schemas: `models`, `matches`, `predictions`, `results`, `scores`
- Column descriptions and data types
- Example queries and their expected SQL
- Constraint: return ONLY the SQL query, nothing else
- Team name note: all team names are Chinese (e.g., 美国, 墨西哥)

### Chat UI

- Inline HTML/CSS/JS served from a Jinja2-like template or f-string
- Message bubbles (user question + system response)
- Results displayed in a styled table with alternating row colors
- SQL query shown in a collapsible `<details>` block below the result
- Loading spinner while DeepSeek responds
- Error messages shown in red
- Input field + send button, submits on Enter key

### Security

- Only `SELECT` queries are allowed to execute (strip `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`)
- Validate the extracted SQL before execution
- Timeout: 30s for DeepSeek API, 10s for SQL execution

### Dependencies

- `requests` (already in requirements.txt) — for DeepSeek API calls
- No new dependencies needed

---

## Feature 3: Dashboard UX Improvements

### Notifications Panel (on index page)

New section at the top of `GET /` showing:

| Item | SQL / Logic |
|------|-------------|
| 🗓 **Today's matches** | `SELECT ... FROM matches WHERE match_date = today` with result status |
| ⏳ **Overdue results** | `SELECT ... FROM matches WHERE match_date < today AND id NOT IN (SELECT match_id FROM results)` |
| 🏆 **Current leader** | Leader model name + avg score from scores table |
| 📊 **Progress** | `COUNT(results) / 72` matches played |
| ⚠️ **Missing predictions** | Models without predictions for matches that have results |

If no issues, show a clean green "All clear" message.

### Telegram Send Button

- Button on index page: **"📤 Send to Telegram"**
- `POST /api/telegram` endpoint calls `telegram_send.main()` via subprocess
- Confirmation toast/message after send
- Shows error if Telegram send fails

### UI Polish

- Notification items are color-coded: green (info), yellow (warning), red (alert)
- Timestamp of last dashboard load shown in footer
- Consistent styling with existing dashboard theme
- Mobile-responsive layout

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `history_chart.py` | **CREATE** | ~80 lines, historical trend chart |
| `dashboard.py` | **MODIFY** | Add chat, notifications, telegram endpoints (~+250 lines) |
| `run_daily.py` | **MODIFY** | Add history_chart step |
| `docs/superpowers/specs/2026-06-16-dashboard-enhancements-design.md` | **CREATE** | This document |

---

## Edge Cases & Error Handling

1. **DeepSeek API down** → Chat returns: "Sorry, the AI query service is unavailable. Try again later."
2. **Invalid SQL returned by DeepSeek** → Show error message with the raw SQL for debugging.
3. **SQL timeout** → 10s query timeout, return friendly error.
4. **No scores yet** → History chart skipped, chat still works (queries other tables).
5. **Empty chat result** → "No results found for your query."
6. **Telegram API fails** → Show error message on dashboard, don't crash.
7. **No matches today** → Notifications shows "No matches scheduled today" in green.
