# Today's Match Forecasts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Today's Match Forecasts" section to the daily HTML report showing each LLM model's predicted scores for matches scheduled today.

**Architecture:** Single-file change to `report.py`. Add one data-fetching function, update the HTML builder to accept new data, and wire it up in `main()`. The section is only rendered when matches exist for today's date.

**Tech Stack:** Python 3, SQLite, HTML (inline template)

**Spec:** `docs/superpowers/specs/2026-06-15-todays-forecast-design.md`

---

### Task 1: Add `_build_todays_forecasts()` function

**Files:**
- Modify: `report.py` (add after `_build_match_rows()` around line 100)

- [ ] **Step 1: Write `_build_todays_forecasts()`**

Add this function after `_build_match_rows()` (after line 100):

```python
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

    # Model display name ordering (matches leaderboard order)
    model_order = ["ChatGPT", "Claude", "Gemini", "Doubao"]

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
                "preds": {m: [] for m in model_order},  # model_name -> list of score strings
            }
        pred_str = f"{pred_h}-{pred_a}"
        matches[match_num]["preds"].setdefault(model_name, []).append(pred_str)

    result = []
    for match_num in sorted(matches.keys()):
        m = matches[match_num]
        pred_cells = []
        for model in model_order:
            scores = m["preds"].get(model, [])
            if not scores:
                pred_cells.append("—")
            else:
                pred_cells.append(" / ".join(scores))
        # Take actual from any row (they're all the same for a match)
        result.append({
            "group": m["group"],
            "home": m["home"],
            "away": m["away"],
            "actual_h": m["actual_h"],
            "actual_a": m["actual_a"],
            "preds": pred_cells,
        })

    return result
```

- [ ] **Step 2: Verify function works by running report**

```bash
cd /Users/william.jiang/my-tests/fifa-2026 && python3 -c "
import sqlite3
from report import _build_todays_forecasts
from datetime import date
conn = sqlite3.connect('forecasts.db')
cur = conn.cursor()
rows = _build_todays_forecasts(cur, date.today())
conn.close()
print(f'Today ({date.today()}): {len(rows)} matches with forecasts')
for r in rows:
    print(f'  {r[\"group\"]}: {r[\"home\"]} vs {r[\"away\"]}')
    for i, m in enumerate(['ChatGPT','Claude','Gemini','Doubao']):
        print(f'    {m}: {r[\"preds\"][i]}')
    actual = f'{r[\"actual_h\"]}-{r[\"actual_a\"]}' if r['actual_h'] is not None else '—'
    print(f'    Actual: {actual}')
"
```

Expected: Shows 4 matches with today's date (June 15) and their predictions.

---

### Task 2: Update `_generate_html()` to render the new section

**Files:**
- Modify: `report.py` (update `_generate_html()` signature and template)

- [ ] **Step 1: Update function signature and add todays_forecasts parameter**

Change line 136-137 from:
```python
def _generate_html(leaderboard: list[dict], match_rows: list[dict],
                   chart_b64: str, today: date) -> str:
```

to:
```python
def _generate_html(leaderboard: list[dict], match_rows: list[dict],
                   chart_b64: str, today: date,
                   todays_forecasts: list[dict] | None = None) -> str:
```

- [ ] **Step 2: Build the today's forecasts HTML block**

Insert after the `rows_html` construction (after `rows_html` block around line 152) and before `match_html` construction:

```python
    todays_html = ""
    if todays_forecasts:
        for m in todays_forecasts:
            actual = (f"{m['actual_h']}-{m['actual_a']}"
                      if m['actual_h'] is not None else "—")
            todays_html += f"""<tr>
              <td>{m['group']}</td>
              <td>{_fmt_team(m['home'])}</td>
              <td>{_fmt_team(m['away'])}</td>
              <td>{m['preds'][0]}</td>
              <td>{m['preds'][1]}</td>
              <td>{m['preds'][2]}</td>
              <td>{m['preds'][3]}</td>
              <td><strong>{actual}</strong></td>
            </tr>\n"""
```

- [ ] **Step 3: Add the section HTML into the template**

Insert after the chart div and before the match results section (after line 224):

```python
    todays_section = ""
    if todays_forecasts:
        todays_section = f"""<h2>🔮 Today's Match Forecasts</h2>
    <div class="match-section">
    <table>
      <tr><th>Group</th><th>Home</th><th>Away</th><th>ChatGPT</th><th>Claude</th><th>Gemini</th><th>Doubao</th><th>Actual</th></tr>
      {todays_html}
    </table>
    </div>
    """
```

Then update the return statement to include `todays_section` between the chart and match results:

```python
    return f"""<!DOCTYPE html>
    ...
    </div>

    {todays_section}

    <h2>📋 Match Results vs Predictions</h2>
    ...
```

- [ ] **Step 4: Verify with a dry-run by reading the updated file**

```bash
cd /Users/william.jiang/my-tests/fifa-2026 && python3 -c "
import ast, sys
with open('report.py') as f:
    source = f.read()
try:
    ast.parse(source)
    print('Syntax OK')
except SyntaxError as e:
    print(f'Syntax error: {e}')
    sys.exit(1)
# Verify signatures
assert '_build_todays_forecasts' in source
assert 'def _generate_html(leaderboard, match_rows, chart_b64, today, todays_forecasts' in source.replace(' | None = None', '').replace('\\n', '\n')
print('All function signatures present')
"
```

Expected: Syntax OK, all functions present.

---

### Task 3: Wire up in `main()`

**Files:**
- Modify: `report.py` (update `main()` function around line 238)

- [ ] **Step 1: Add call to `_build_todays_forecasts()` in `main()`**

Change `main()` to add the forecasts call between `_build_match_rows` and the `conn.close()`:

After line 245 (`match_rows = _build_match_rows(cur)`), add:
```python
    todays_forecasts = _build_todays_forecasts(cur, today)
```

Then pass it to `_generate_html()` on line 253:
```python
    html = _generate_html(leaderboard, match_rows, chart_b64, today, todays_forecasts)
```

The full `main()` after changes should look like:
```python
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
```

- [ ] **Step 2: Run the full report pipeline to verify**

```bash
cd /Users/william.jiang/my-tests/fifa-2026 && python3 report.py
```

Expected: 
```
Report saved: reports/2026-06-15.html (XXXX bytes)
```
The HTML file should contain a "🔮 Today's Match Forecasts" table with 4 matches.

- [ ] **Step 3: Open the report and inspect the new section**

```bash
cd /Users/william.jiang/my-tests/fifa-2026 && grep -c 'Today.*Match Forecasts' reports/2026-06-15.html
```

Expected: `1` (section is present)

---

### Self-Review Checklist

- [ ] **Spec coverage**: Spec requirement "table with Group, Home, Away, Model columns, Actual" is implemented in Task 2. "Only render if matches today" via the `if todays_forecasts:` guard. "Gemini dual scenarios merged" via `" / ".join(scores)` in Task 1.
- [ ] **Placeholder scan**: No TBDs, TODOs, "add error handling", or other placeholders. Every code block is complete.
- [ ] **Type consistency**: `_build_todays_forecasts` returns `list[dict]` in Task 1 and is used as `todays_forecasts: list[dict] | None = None` in Task 2. `preds` is a `list[str]` of length 4. Field names match across tasks.

