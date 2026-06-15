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
│   └── gemini.md
├── docs/
│   ├── claude-1.md        # Architecture plan
│   └── wc2026_system_architecture.png
├── forecasts.db           # SQLite (created by parse_forecasts.py)
├── parse_forecasts.py     # One-time: parse all 4 files → SQLite
├── fetch_results.py       # Daily: football-data.org API → DB
├── score.py               # Daily: compare predictions vs results
├── report.py              # Daily: HTML + chart generation
├── telegram_send.py       # Daily: push report to Telegram
├── run_daily.py           # Orchestrator
├── com.wc2026.tracker.plist  # macOS launchd schedule
├── .gitignore
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
2. `fetch_results.py` ← implementation needed
3. `score.py` ← implementation needed
4. `report.py` ← implementation needed
5. `telegram_send.py` ← implementation needed
6. `run_daily.py` ← orchestrator skeleton, will call 2-5

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
