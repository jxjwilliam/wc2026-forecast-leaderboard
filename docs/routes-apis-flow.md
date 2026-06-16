# WC2026 Forecast Tracker — Routes, APIs & Data Flow

## 1. Dashboard Routes ↔ Menu Navigation

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚽ WC2026 Forecast Tracker    [📊 Report] [🏆 Bracket] [💬 Chat] [📤] │  ← same on every page
└─────────────────────────────────────────────────────────────────┘
```

| Nav Label | Route | What it does | What you see |
|-----------|-------|-------------|--------------|
| *(logo)* `⚽ WC2026 Forecast Tracker` | `GET /` | Overview page | Notifications panel, score history chart, lists of past reports & past brackets |
| `📊 Report` | `GET /latest` | Redirect → most recent daily report | Full daily report: leaderboard, accuracy chart, match forecasts, model comparison |
| `🏆 Bracket` | `GET /knockout` | Redirect → most recent knockout page | 32-team bracket: R32 → R16 → QF → SF → Final |
| `💬 Chat` | `GET /chat` | NL→SQL chat interface | Chat box where you ask questions in English, get results from the database |
| `📤` (button) | `POST /api/telegram` | Send latest report to Telegram | Toast notification: "✅ Sent!" or error |

### Behind the scenes

| Hidden Route | Type | Purpose | How you reach it |
|-------------|------|---------|-----------------|
| `GET /reports/*` | static file mount | Serves all generated HTML reports + PNG charts | Indirectly — `/latest` redirects to `/reports/2026-06-16.html`, `/knockout` redirects to `/reports/knockout-2026-06-16.html`. Also linked directly from the Overview page tables |
| `GET /favicon.ico` | inline SVG | ⚽ favicon | Browser auto-request |

### The mental model

```
         ┌──────────────────┐
         │  / (Overview)    │  ← Notifications, chart, links to everything
         │  Logo click ─────┼──┐
         └──────────────────┘  │
                               ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │  /latest          │  │  /knockout       │  │  /chat            │
    │  → daily report   │  │  → bracket page  │  │  → chat query     │
    │  /reports/{d}.html│  │  /reports/ko-..  │  │  (standalone)     │
    └──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 2. API Endpoints ↔ Python Backing

| Endpoint | Method | Python Handler | Backing Script(s) | What happens |
|----------|--------|---------------|-------------------|-------------|
| `/api/chat` | POST | `dashboard.py :: api_chat()` | `forecasts.db` (SQLite) | Receives NL question → calls DeepSeek API → gets SQL → executes against DB → returns JSON `{columns, rows, sql}` |
| `/api/telegram` | POST | `dashboard.py :: api_telegram()` | `telegram_send.py :: main()` | Subprocess‑spawns `telegram_send.py` → builds leaderboard text from DB → sends to Telegram channel via bot |

### Script → Function map (full project)

| Script | Entry Point | Purpose | Called by |
|--------|------------|---------|-----------|
| `dashboard.py` | `main()` / uvicorn | FastAPI web server (overview, reports, chat, Telegram trigger) | `python3 dashboard.py` |
| `run_daily.py` | `main()` | Orchestrates the daily pipeline | `python3 run_daily.py` |
| `fetch_results.py` | `main()` | Fetch match results from football-data.org API → DB | `run_daily.py` |
| `score.py` | `main()` | Compare predictions vs results, compute scores → DB | `run_daily.py` |
| `history_chart.py` | `main()` | Generate multi-model score history line chart PNG | `run_daily.py` |
| `knockout.py` | `main()` | Compute group standings, simulate knockout bracket → HTML | `run_daily.py` |
| `report.py` | `main()` | Generate daily report HTML + charts | `run_daily.py` |
| `telegram_send.py` | `main()` | Send leaderboard text + report to Telegram | `run_daily.py`, `dashboard.py POST /api/telegram` |
| `parse_forecasts.py` | `main()` | (One‑time) Parse 6 LLM forecast files → SQLite | `python3 parse_forecasts.py` |
| `fetch_deepseek_forecast.py` | `main()` | (One‑time) Call DeepSeek API → `data/deepseek.md` | `python3 fetch_deepseek_forecast.py` |

---

## 3. Data Flow (Mermaid)

### Daily pipeline (`run_daily.py`)

```mermaid
flowchart LR
    API["football-data.org"] --> fetch["fetch_results.py"]
    fetch --> DB[("forecasts.db")]
    DB --> score["score.py"]
    score --> DB
    
    DB --> hc["history_chart.py"]
    hc --> PNG["reports/history.png"]
    
    DB --> ko["knockout.py"]
    ko --> KO_HTML["reports/knockout-{date}.html"]
    ko --> ko_summary["(console summary text)"]
    
    DB --> report["report.py"]
    report --> RPT_HTML["reports/{date}.html"]
    RPT_HTML --> PNG
    
    RPT_HTML --> tg["telegram_send.py"]
    tg --> Telegram["📱 Telegram Channel"]
```

### Web dashboard (`dashboard.py`)

```mermaid
flowchart LR
    subgraph Browser
        OVERVIEW["/ Overview"]
        REPORT["/latest → /reports/{d}.html"]
        BRACKET["/knockout → /reports/ko-{d}.html"]
        CHAT["/chat"]
    end

    subgraph Server[dashboard.py]
        idx["index()"]
        lv["latest()"]
        ko["knockout()"]
        cp["chat_page()"]
        apichat["api_chat()"]
        apitg["api_telegram()"]
    end

    subgraph Data
        DB[("forecasts.db")]
        REPORTS["reports/*.html, *.png"]
        DS["DeepSeek API"]
        TG_SCRIPT["telegram_send.py"]
    end

    OVERVIEW --> idx
    REPORT --> lv --> REPORTS
    BRACKET --> ko --> REPORTS
    CHAT --> cp
    
    CHAT -->|"POST /api/chat"| apichat
    apichat --> DS -->|"NL→SQL"| apichat
    apichat -->|"SQL query"| DB -->|"JSON result"| CHAT
    
    OVERVIEW -->|"📤 button → POST /api/telegram"| apitg
    apitg --> TG_SCRIPT --> Telegram["📱 Telegram"]
    
    idx --> DB -->|"notifications"| idx
    idx --> REPORTS -->|"report list"| idx
```

### NL→SQL chat flow

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant dashboard.py
    participant DeepSeek API
    participant forecasts.db

    User->>Browser: Type question (English)
    Browser->>dashboard.py: POST /api/chat {question}
    dashboard.py->>DeepSeek API: POST /chat/completions (prompt + schema)
    DeepSeek API-->>dashboard.py: SQL query string
    dashboard.py->>forecasts.db: execute(SQL)
    forecasts.db-->>dashboard.py: {columns, rows}
    dashboard.py-->>Browser: JSON {columns, rows, sql}
    Browser-->>User: Render results table
```

### Telegram send flow

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant dashboard.py
    participant telegram_send.py
    participant forecasts.db
    participant Telegram

    User->>Browser: Click 📤 button
    Browser->>dashboard.py: POST /api/telegram
    dashboard.py->>telegram_send.py: subprocess(telegram_send.py)
    telegram_send.py->>forecasts.db: query leaderboard
    forecasts.db-->>telegram_send.py: scores data
    telegram_send.py->>Telegram: sendMessage (leaderboard)
    telegram_send.py->>Telegram: sendDocument (report HTML)
    telegram_send.py-->>dashboard.py: exit code 0
    dashboard.py-->>Browser: JSON {status: "ok"}
    Browser-->>User: Toast "✅ Sent!"
```
