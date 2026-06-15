# WC2026 Forecast Tracker

Tracks 4 LLM forecasts (ChatGPT, Claude, Gemini, Doubao) for the 2026 FIFA World Cup, fetches real results daily, scores each model, and delivers a ranked leaderboard to Telegram.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and fill in your keys
# (or create .env with the variables listed below)
cp .env.example .env

# One-time: parse all forecast files into SQLite
python3 parse_forecasts.py

# (Optional) Schedule daily run via launchd
cp com.wc2026.tracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wc2026.tracker.plist
```

## Daily Pipeline

```bash
python3 run_daily.py
```

This runs: fetch_results → score → report → telegram_send.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `FOOTBALL_DATA_API` | Yes | football-data.org API key |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token (from BotFather) |
| `TELEGRAM_CHAT_ID` | Yes | Telegram chat ID to send reports to |

## Scoring

Tiers are **cumulative** — a match can earn all three if conditions are met.

| Tier | Points | Condition |
|---|---|---|
| Exact score | 3 pts | Predicted score matches exactly |
| Correct result | 1 pt | Win/draw/loss direction correct |
| Goal difference | +0.5 | Goal diff within 1 of actual |

### Model-specific rules

- **Gemini**: both scenarios (`scenario_1` / `scenario_2`) scored independently (not best-of-two). Each is a separate row in the model comparison.
- **Claude**: confidence % multiplier applies to the **result tier** (1 pt) and **diff bonus** (0.5 pt), but NOT to the exact-score tier (3 pts). High confidence on a correct result earns more.
- **ChatGPT Group K**: source data corrected (Jamaica → Congo DRC).

## Project Structure

```
data/            LLM forecast source files
docs/            Architecture plan + diagram
forecasts.db     SQLite database (generated)
reports/         Daily HTML reports + charts (generated)
.env             Environment variables (API keys)
*.py             Pipeline modules
com.*.plist      macOS launchd schedule
```

## Pipeline

Source files → parse_forecasts.py → forecasts.db → fetch_results.py → score.py → report.py → telegram_send.py → Telegram
