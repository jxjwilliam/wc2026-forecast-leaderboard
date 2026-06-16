# Knockout Predictor + Web Dashboard — Design Spec

## Overview

Two additions to the WC2026 Forecast Tracker:

1. **Knockout Predictor** — Determines group standings from actual + predicted results using the current leader model, simulates the full knockout bracket, and outputs an HTML bracket page + Telegram summary.
2. **Web Dashboard** — Minimal FastAPI static server that serves the generated HTML reports and bracket pages with a date-indexed landing page.

---

## Feature 5: Knockout Predictor (`knockout.py`)

### Data Flow

```
scores table → identify leader model (highest avg total)
                    ↓
matches + results + predictions → compute group standings per group (A-L)
                    ↓
top 2 per group + 8 best 3rd-place → 32 qualifiers
                    ↓
Round of 32 fixed bracket → progress round by round
                    ↓
each knockout match: compare group stage record of the two teams
                    ↓
HTML bracket page (reports/knockout-{date}.html)
                    ↓
Telegram summary text (returned for run_daily.py)
```

### Group Standings Computation

For each group A-L (4 teams, 6 matches):
- If `results` row exists for a match → use actual home_score/away_score
- If no result → use leader model's predicted home_score/away_score
- Per team: 3 pts win, 1 pt draw, 0 pt loss
- Tiebreakers: points → goal difference → goals scored → alphabetical
- Position determined by descending sort

### Qualification Rules (48 → 32)

- 12 group winners (position 1) — qualify
- 12 group runners-up (position 2) — qualify
- 8 best 3rd-place finishers across all 12 groups — qualify
  - Sorted by: points → goal difference → goals scored

### Round of 32 Bracket Pairings

Standard 48-team World Cup format pairings:

| Match # | Home | Away |
|---------|------|------|
| 1 | Winner A | 3rd B/E/F |
| 2 | Winner C | 3rd A/D/F |
| 3 | Winner E | 3rd C/D |
| 4 | Winner G | 3rd A/B/H |
| 5 | Winner I | 3rd B/E/H |
| 6 | Winner J | 3rd F/G/H |
| 7 | Winner K | 3rd D/E/H |
| 8 | Winner L | 3rd A/C/G |
| 9 | Runner-up A | Runner-up B |
| 10 | Runner-up C | Runner-up D |
| 11 | Runner-up E | Runner-up F |
| 12 | Runner-up G | Runner-up H |
| 13 | Runner-up I | Runner-up J |
| 14 | Runner-up K | Runner-up L |
| 15 | Winner B | Winner F |
| 16 | Winner D | Winner H |

### Knockout Match Resolution

**Important: models only predicted group stage matches (72 total). There are no direct knockout predictions in the DB.**

For each knockout match between Team X and Team Y:
1. Compare their simulated group stage performance:
   - Total points in group stage (higher wins)
   - Goal difference (tiebreak)
   - Goals scored (tiebreak)
2. The team with better group record advances
3. Winner recorded, advances to next round

### Round Flow

```
Round of 32 (16 matches)
    → Round of 16 (8 matches)
        → Quarter-finals (4 matches)
            → Semi-finals (2 matches)
                → 3rd-place playoff (1 match)
                → Final (1 match)
```

### Output: HTML Bracket Page

- `reports/knockout-{date}.html`
- Visual bracket tree using HTML/CSS
- Each match slot shows: team names, group stage record (pts/GD)
- Color coding:
  - Green: result confirmed by actual match
  - Blue: predicted by leader model
  - Gray: team placed but outcome TBD (if no data)
- Header: "🏆 Knockout Prediction — based on [Leader Model] forecasts"

### Output: Telegram Summary (text return)

`knockout.main()` returns a `str | None`:
```
🏆 Knockout Prediction (based on {leader})
Groups decided: {qualifiers_count} teams advance
Round of 32: {predicted_matchups}
...
Predicted Champion: {team}
```
Pipeline caller prints this and optionally sends to Telegram.

---

## Feature 6: Web Dashboard (`dashboard.py`)

### Framework

- **FastAPI** with `fastapi[standard]` (includes uvicorn)
- Single file, no router modules

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Index page — lists all report dates as links |
| GET | `/latest` | Redirect to most recent report |
| GET | `/knockout` | Redirect to most recent knockout page |
| Static | `/reports/{filename}` | Files from `reports/` directory |

### Index Page

- Minimal HTML listing all `YYYY-MM-DD.html` files found in `reports/`
- Links to knockout pages where they exist
- Latest report highlighted at top
- No extra dependencies — pure inline HTML

### Running

```bash
python3 dashboard.py
# → Serving at http://127.0.0.1:8080
```

---

## Pipeline Integration

### `run_daily.py` changes

Add `knockout.main()` after scoring, pass its output to `report.main()` or handle separately:

```
fetch_results → score → knockout → report → telegram_send
```

### `requirements.txt` changes

Add: `fastapi[standard]`

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `knockout.py` | **CREATE** | ~250 lines, knockout predictor |
| `dashboard.py` | **CREATE** | ~80 lines, FastAPI web server |
| `run_daily.py` | **MODIFY** | Add knockout step |
| `requirements.txt` | **MODIFY** | Add fastapi dependency |
| `docs/superpowers/specs/2026-06-16-knockout-dashboard-design.md` | **CREATE** | This document |

---

## Edge Cases & Constraints

1. **No results yet** — All group matches use leader predictions. Still produces a bracket.
2. **No leader** (no scores) — Print warning, return None, no HTML generated.
3. **Partial group stage** — Mix of actual results + leader predictions. Tiebreakers work either way.
4. **Empty reports/** directory — Dashboard shows "No reports yet."
5. **Standalone run** — Both files work independently (`python3 knockout.py`, `python3 dashboard.py`).
6. **No knockout predictions exist** — Group stage record comparison is the sole method for knockout outcomes.
