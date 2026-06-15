# WC2026 Forecast Tracker — Agent Guide

## Project Overview

Ingest 4 LLM forecasts (ChatGPT, Claude, Gemini, Doubao) for the 2026 World Cup,
fetch real results daily, score each model, and deliver a ranked comparison via Telegram.

## Project Structure

```
fifa-2026/
├── data/                   # LLM forecast source files
│   ├── chatgpt.md
│   ├── claude.pdf
│   ├── doubao.md
│   ├── gemini.md
│   └── teams-groups.md    # Ground truth: 48 teams × 12 groups
├── docs/
│   ├── claude-1.md        # Architecture plan
│   └── wc2026_system_architecture.png
├── .env.example           # Template for API keys
├── .gitignore
├── forecasts.db           # SQLite (created by parse_forecasts.py)
├── parse_forecasts.py     # One-time: parse all 4 files → SQLite
├── fetch_results.py       # Daily: football-data.org API → DB
├── score.py               # Daily: compare predictions vs results
├── report.py              # Daily: HTML + chart generation
├── telegram_send.py       # Daily: push report to Telegram
├── run_daily.py           # Orchestrator
├── com.wc2026.tracker.plist  # macOS launchd schedule
└── requirements.txt
```

## Key Design Decisions

- **Canonical match list** defined in `CANONICAL_MATCHES` (72 matches, 12 groups A-L)
- **Team names normalised** bi-directionally (Chinese ↔ English) in TEAM_MAP
- **Gemini dual scenarios**: stored as `scenario_1` / `scenario_2`, scored independently
- **ChatGPT Group K correction**: source data updated (Jamaica → Congo DRC)
- **Scoring tiers**: exact=3pt, correct result=1pt, goal diff within 1=+0.5pt

## Pipeline Order (no step runs without its predecessor)

1. `parse_forecasts.py` ← COMPLETE
2. `fetch_results.py` ← COMPLETE
3. `score.py` ← COMPLETE
4. `report.py` ← COMPLETE
5. `telegram_send.py` ← COMPLETE (blocked on user messaging bot first)
6. `run_daily.py` ← COMPLETE (orchestrator wiring all 5 steps)

## Running

```bash
# One-time ingestion
python3 parse_forecasts.py

# Daily pipeline
python3 run_daily.py
```

## Data Flow

```
Source files → parse_forecasts.py → forecasts.db
                                      ↓
football-data.org → fetch_results.py → forecasts.db
                                      ↓
                         score.py → forecasts.db
                                      ↓
                         report.py → reports/*.html + *.png
                                      ↓
                         telegram_send.py → Telegram channel
```
