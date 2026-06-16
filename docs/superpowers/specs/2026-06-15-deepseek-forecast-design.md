# DeepSeek Forecast Integration — Design Spec

## Problem

The project tracks 4 LLM forecasts (ChatGPT, Claude, Gemini, Doubao). User has a
DeepSeek API key configured in `.env` and wants DeepSeek added as a 5th model.

## Solution

### Data Flow
1. **`fetch_deepseek_forecast.py`** (new) — Calls DeepSeek chat API with a prompt
   containing all 72 World Cup matchups, asks for group-by-group score predictions,
   saves the response to `data/deepseek.md` as a static markdown table.
2. **`parse_forecasts.py`** (modified) — Add `parse_deepseek()` function matching
   the existing pattern. Register `deepseek` model. Safe to re-run (INSERT OR IGNORE).
3. **`report.py`** (modified) — Add `"DeepSeek"` to `model_order` in the forecast
   section.

### Output Format for `data/deepseek.md`

```markdown
# DeepSeek 2026 World Cup Predictions

| Group | Match | Score |
| --- | --- | --- |
| A | 墨西哥 vs 南非 | 2-0 |
| A | 韩国 vs 捷克 | 1-1 |
...
```

### Files Changed

| File | Change |
|------|--------|
| `fetch_deepseek_forecast.py` | Create — API call → static file |
| `parse_forecasts.py` | Add parser + model registration |
| `report.py` | Add "DeepSeek" to model_order |

### Scoring Relevance

DeepSeek predictions will be scored the same as all other models — the existing
`score.py` handles any model in the `predictions` table.
