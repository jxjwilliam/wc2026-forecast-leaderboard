# Today's Match Forecasts — Design Spec

## Problem

The daily report shows past match results vs predictions (scored), but doesn't
show what each LLM *predicts* for matches happening **today**. Users want to see
at a glance: "What does each model think will happen in today's games?"

## Solution

Add a new section to the HTML report titled **"🔮 Today's Match Forecasts"**
showing a wide table with one row per match and one column per model.

## Table Layout (Option A — approved)

| Group | Home | Away | ChatGPT | Claude | Gemini | Doubao | Actual |
|-------|------|------|---------|--------|--------|--------|--------|

- **One row per match** where `matches.match_date == date.today()`
- **Model columns** show predicted score as `home-away` (e.g. `2-1`)
- **Gemini** displays both scenarios as `scenario_1 / scenario_2` (e.g. `2-1 / 1-1`)
- **Actual column** shows the real score if a `results` row exists, else `—`

## Data Query

```sql
SELECT mt.group_name, mt.home_team, mt.away_team,
       m.display_name, p.home_score, p.away_score, p.scenario,
       r.home_score AS actual_h, r.away_score AS actual_a
FROM matches mt
LEFT JOIN predictions p ON p.match_id = mt.id
JOIN models m ON m.id = p.model_id
LEFT JOIN results r ON r.match_id = mt.id
WHERE mt.match_date = :today
ORDER BY mt.match_number, m.id, p.scenario
```

## Implementation

- **File**: `report.py` only
- **New function**: `_build_todays_forecasts(cur, today) -> list[dict]`
- **Query scope**: All matches with `match_date == today`
- **Model ordering**: ChatGPT → Claude → Gemini → Doubao (same as leaderboard)
- **Gemini dual scenarios**: Merge into a single cell: `S1 / S2`
- **Section visibility**: Only rendered if there are matches today (empty otherwise)
- **HTML/CSS**: Reuse existing table styles; no new CSS needed

## Edge Cases

- **No matches today**: Section is omitted entirely (not rendered empty)
- **Partial scenarios**: If Gemini only has one scenario (not both), show just that one
- **No predictions for a match**: Cell shows `—`; should not happen with canonical data
- **Results exist**: Actual column shows `home-actual vs away-actual`
- **Results don't exist**: Actual column shows `—`

## Files Changed

| File | Change |
|------|--------|
| `report.py` | Add `_build_todays_forecasts()`, modify `_generate_html()`, call new function in `main()` |

No other files need changes.
