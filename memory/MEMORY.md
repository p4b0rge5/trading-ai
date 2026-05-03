# Memory — Trading AI Project

## Project: Trading AI App
**Started:** 2026-04-30
**Last Updated:** 2026-05-03
**Status:** Fase 1-6 ✅ — Full app running with live paper trading, notifications, dual theme

## Public URL
- **Dashboard:** https://effort-grow-umbrella-vivid.2n6.me/trading/
- **API:** https://effort-grow-umbrella-vivid.2n6.me/trading/api/v1/...
- **Swagger Docs:** https://effort-grow-umbrella-vivid.2n6.me/trading/docs

## GitHub
- **Repo:** https://github.com/p4b0rge5/trading-ai
- **Branch:** main
- **Remote:** configured via git credential helper
- **Note:** .env and *.db ARE tracked (removed from .gitignore per user request)

## What's Built

### Engine (Fase 1)
- `engine/models.py` — Pydantic models: StrategySpec, IndicatorSpec, EntryCondition, ExitCondition, RiskManagement
- `engine/indicators.py` — 9 indicators (SMA, EMA, WMA, RSI, MACD, Bollinger, Stochastic, ATR, ADX) with TA-Lib + NumPy fallback
- `engine/interpreter.py` — Bar-by-bar strategy interpreter with entry/exit evaluation, SL/TP/ATR-stop/time-based exits. Supports `start_from` and `live_mode` for incremental evaluation.
- `engine/backtester.py` — Full backtest with metrics (win rate, Sharpe, drawdown, profit factor) + Matplotlib chart generation
- `engine/sample_data.py` — OHLCV generator with GARCH-like volatility
- `engine/data_fetcher.py` — Real market data via yfinance (26 forex/crypto pairs)
- `engine/mql5_generator.py` — MQL5 EA code generation from StrategySpec (190+ lines)

### Prompt System (Fase 2)
- `prompt_system/schema.py` — JSON Schema export from Pydantic StrategySpec
- `prompt_system/prompts.py` — System prompt with rules, 3 few-shot examples
- `prompt_system/llm_client.py` — OpenAI client (real) + Smart Mock LLM (parses PT/EN prompts) with retry loop
- `prompt_system/orchestrator.py` — Full pipeline: prompt → LLM → validate → backtest → result
- **27/27 prompts** passed test suite

### Backend API (Fase 3)
- `api/config.py` — Settings via env vars / .env
- `api/database.py` — SQLAlchemy: User, Strategy, Backtest, Trade, LiveSession, LiveTrade (SQLite → PostgreSQL ready)
- `api/auth.py` — JWT auth: bcrypt passwords, create/decode tokens, get_current_user
- `api/schemas.py` — Pydantic request/response models (including LiveSessionCreate with optional webhook_url)
- `api/routes_auth.py` — POST /register, POST /login (OAuth2), GET /me
- `api/routes_strategies.py` — CRUD /strategies/, POST /from-prompt, GET /{id}/export/mql5
- `api/routes_backtests.py` — POST /backtests/, GET /summary, GET /{id}
- `api/routes_live.py` — CRUD /live/sessions/, GET /{id}, POST /{id}/stop, GET /{id}/trades. Enriches DB session data with live in-memory state (equity, trades, P&L) from session registry for running sessions.
- `api/routes_data.py` — GET /data/symbols, GET /data/ohlcv, GET /data/price/{symbol}
- `api/app.py` — FastAPI with CORS, lifespan, static frontend mount

### Live Trading (Fase 6) + Paper Trading
- `engine/live_trading/metaapi_client.py` — MetaApi SDK v29 wrapper: WebSocket connection, candle subscriptions, order execution (buy/sell/close), account info, event callbacks
- `engine/live_trading/paper_client.py` — Paper trading client: real-time prices via yfinance, in-memory order simulation, margin/P&L/SL/TP tracking. **Crypto PnL uses contract_size=1** (not forex 100K). Same event system as MetaApiClient.
- `engine/live_trading/live_engine.py` — Bar builder from candles, strategy interpreter evaluation on bar close (with `start_from` + `live_mode`), auto-trading loop with 60s yfinance polling + live price tick updates
- `engine/live_trading/order_manager.py` — Trade lifecycle: open/close positions, SL/TP, position tracking. ATR stop with 0.1% default for crypto.
- `engine/live_trading/__init__.py` — LiveSession: two modes — "paper" (yfinance, free) or "live" (MetaApi, real money). Registers into global session_registry on start.
- `engine/live_trading/session_registry.py` — Global in-memory registry of active LiveSession instances. API routes use this to enrich DB data with live state (equity, open trades, P&L).

### Notifications
- `engine/notifications.py` — NotificationService with webhook + local callback support
- Events: trade_opened, trade_closed, signal_triggered, session_started, session_stopped
- Integrated into: OrderManager (on trade open/close), LiveSession (on start/stop)
- Webhook: HTTP POST with JSON payload (aiohttp with urllib fallback)

### Frontend Dashboard (Fase 4 + UI Redesign)
- `frontend/index.html` — SPA entry point
- `frontend/css/style.css` — **Dual theme** (dark default + light theme) with CSS custom properties, responsive
- `frontend/js/app.js` — Core: API client, Auth service, Router, Toast, helpers
- `frontend/js/layout.js` — App layout: sidebar nav + main content wrapper + **theme toggle**
- `frontend/js/pages_auth.js` — Login & Register forms
- `frontend/js/pages_dashboard.js` — Stats, quick-create, recent backtests, strategies list
- `frontend/js/pages_strategies.js` — Strategies table with delete
- `frontend/js/pages_create.js` — Prompt → Strategy + live backtest results
- `frontend/js/pages_strategy_detail.js` — Indicators, rules, risk, backtest history
- `frontend/js/pages_backtest.js` — Run backtest, results with TradingView chart + trades table
- `frontend/js/pages_live.js` — Live trading dashboard: start/stop sessions, monitor equity, trade table with open/closed, session detail modal panel
- `frontend/js/trade_audio.js` — **Web Audio API notification sounds** — synthetic tones (no external files), visual screen flashes, toggle control
- **Tech:** Vanilla JS SPA (no framework), hash-based routing with dynamic `:param` support, TradingView Lightweight Charts

### Database
- SQLite (`trading_ai.db`, tracked in repo)
- Tables: users (11), strategies (11), backtests (5), trades (669), live_sessions (15), live_trades
- Foreign keys with ON DELETE CASCADE (enabled per-connection via SQLAlchemy event listener)

## Architecture
```
trading-ai/
├── api/                       # FastAPI backend
│   ├── app.py                # Main app, CORS, static mount
│   ├── config.py             # Settings
│   ├── database.py           # SQLAlchemy models + session
│   ├── auth.py               # JWT + bcrypt
│   ├── schemas.py            # Pydantic models
│   ├── routes_auth.py        # /api/v1/auth/*
│   ├── routes_strategies.py  # /api/v1/strategies/*
│   ├── routes_backtests.py   # /api/v1/backtests/*
│   ├── routes_live.py        # /api/v1/live/* (sessions, trades)
│   └── routes_data.py        # /api/v1/data/*
├── engine/                   # Trading engine
│   ├── models.py, indicators.py, interpreter.py, backtester.py
│   ├── sample_data.py, data_fetcher.py, mql5_generator.py
│   ├── notifications.py      # Webhook + callback notification service
│   └── live_trading/         # Live trading subsystem
│       ├── __init__.py       # LiveSession class
│       ├── metaapi_client.py # Real MetaApi WebSocket
│       ├── paper_client.py   # Paper trading (yfinance)
│       ├── live_engine.py    # Bar builder + evaluation loop
│       ├── order_manager.py  # Trade lifecycle + SL/TP
│       └── session_registry.py # Global in-memory session registry
├── prompt_system/            # LLM integration
│   ├── schema.py, prompts.py, llm_client.py, orchestrator.py
├── frontend/                 # SPA dashboard
│   ├── index.html
│   ├── css/style.css         # Dual theme (dark/light)
│   └── js/{app,layout,pages_*,trade_audio}.js
├── scripts/                  # Entry points
│   └── run_server.py
├── .env                      # Environment config (TRACKED in repo)
└── trading_ai.db             # SQLite database (TRACKED in repo)
```

## Key Decisions
- MQL5 as export standard (not MQL4)
- Forex first, then crypto (BTCUSD, ETHUSD)
- Pure NumPy fallback (no TA-Lib hard dependency)
- Strategy spec JSON as central data format
- SQLite for dev, PostgreSQL for production
- Vanilla JS SPA (no build step needed)
- Hash-based routing (no server config needed for SPA routes)
- TradingView Lightweight Charts for equity curves
- Dual theme (dark default + light) with CSS custom properties
- Web Audio API for notification sounds (zero external assets)

## Deployment
- **Server:** `python3 scripts/run_server.py` → uvicorn on :8081
- **Caddy:** `/etc/caddy/conf.d/trading-app.caddy` → `/trading/*` → `localhost:8081`
- **Public:** `https://effort-grow-umbrella-vivid.2n6.me/trading/`
- **Active sessions (2026-05-03):** Sessions 24 (Turbo EMA 5/13) and 25 (Hyper EMA 3/7) in paper mode, polling yfinance every 60s. Started after bugfix restart.

## Bugs Fixed
- Hash routing: `#/register` vs `/register` mismatch → normalized hash
- Syntax error: `if entries.length === 0)` missing `(` in pages_backtest.js
- `setActiveNav` not defined: moved from pages_backtest.js to layout.js (load order)
- Router: object-key lookup can't match dynamic routes → regex-based matching with `:param` support
- Cache: JS version query params (`?v=20260430b`) + meta no-cache tags for mobile
- ATR numpy concatenate syntax error (missing bracket) in live engine
- Live engine interpreter: `start_from` and `live_mode` to prevent re-trading historical signals
- Paper client: crypto PnL used forex contract_size=100K causing massive swings → now uses contract_size=1 for BTC/ETH/SOL/XRP
- Session detail panel: render but forgot to show (modal never displayed)
- Order manager: ATR stop with None values → 0.1% default for crypto symbols
- Paper client: handle sl=None and tp=None in _trade()
- **Interpreter always-buy bug (2026-05-03):** `_check_entry()` defaulted side="buy" and only switched to sell if a crossunder condition existed. Now derives side from the primary crossover/crossunder condition type.
- **Duplicate entries (2026-05-03):** `_evaluate()` in live_engine used `set(_open_trades.keys())` (trade_id strings like "12345") but compared against `"buy_BTCUSD"` → always True → duplicate entries on every poll. Now uses `{t.side for t in _open_trades.values()}` → correctly deduplicates by side.

## TODO / Next
- [x] Paper trading with real-time yfinance data
- [x] In-memory session registry for live data
- [x] Notification service (webhooks + audio)
- [x] Dual theme (light/dark)
- [ ] WebSocket for real-time backtest progress
- [ ] Strategy comparison view
- [ ] PostgreSQL migration for production
- [ ] Real OpenAI integration (swap use_mock_llm=false + set API key)
- [ ] Alpha Vantage / other data providers as fallback
- [ ] Strategy performance ranking & leaderboard
