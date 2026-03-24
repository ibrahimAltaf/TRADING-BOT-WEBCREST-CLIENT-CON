# Complete System Documentation

## 1. Document Purpose

This document explains the full trading system from A to Z in a human-readable
format. It is written as a business + technical reference so a client, developer,
tester, or future maintainer can understand:

1. What the system does.
2. Which technologies are used.
3. How frontend and backend talk to each other.
4. How trading decisions are created.
5. How ML is used.
6. How paper trading, live trading, and monitoring work.
7. How to run, test, and validate the system.

This system has two main codebases inside the workspace:

- Backend: `bot new backend`
- Frontend dashboard: `trading-bot-dashboard`

---

## 2. System Summary

This project is an AI-assisted trading platform built around a FastAPI backend
and a React dashboard.

At a high level, the system provides:

- Exchange integration for Binance spot/testnet.
- Rule-based adaptive trading.
- Optional ML-assisted signal refinement using an LSTM model.
- Paper trading and live trading workflows.
- Backtesting and validation endpoints.
- Health monitoring and runtime transparency.
- Dashboard visibility for balances, orders, trades, decisions, logs, and status.

The system is designed so a user can:

1. Connect to exchange/testnet.
2. See balances, prices, orders, trades, and positions.
3. Run paper trading or live auto-trading.
4. Inspect why a BUY, SELL, or HOLD decision was made.
5. Compare rule-only behavior versus ML-assisted behavior.
6. Review trade-by-trade outcomes for analysis and audits.

---

## 3. Technology Stack

### Backend

- Python 3.11
- FastAPI
- Uvicorn
- SQLAlchemy
- PostgreSQL via `psycopg2-binary`
- APScheduler
- pandas / numpy / pyarrow
- TensorFlow for LSTM inference
- scikit-learn
- python-binance
- ccxt
- passlib + JWT auth helpers

### Frontend

- React
- TypeScript
- Vite
- TanStack Query
- Axios
- Tailwind-style utility classes
- Lightweight Charts

---

## 4. Folder Structure

### Backend

Important backend folders:

- `src/main.py`
  - FastAPI app entry point.
- `src/api/`
  - HTTP routes grouped by business area.
- `src/core/`
  - Configuration, auth helpers, logging/config support.
- `src/db/`
  - Database base, session, and models.
- `src/live/`
  - Adaptive strategy engine and live auto-trade logic.
- `src/ml/`
  - ML feature selection, model resolution, inference, dataset, training.
- `src/scheduler/`
  - Interval scheduler for live auto-trading.
- `src/features/`
  - Technical indicators and feature building.
- `src/tests/`
  - Automated backend tests.
- `docs/`
  - API contract and architecture documentation.

### Frontend

Important frontend folders:

- `src/App.tsx`
  - Main app routes and shell.
- `src/components/`
  - Shared UI components.
- `src/pages/`
  - Page-level views like Dashboard, Exchange, Paper, Status Summary.
- `src/apis/`
  - API clients and query hooks.
- `src/lib/http.ts`
  - Axios client and error normalization.

---

## 5. Runtime Architecture

The runtime architecture is:

1. React dashboard sends HTTP requests to FastAPI.
2. FastAPI routes call services or engines.
3. Services read/write database tables.
4. Exchange client talks to Binance.
5. Scheduler can trigger periodic live trade cycles.
6. ML model can optionally assist rule-based decisions.
7. Dashboard reads decisions, performance, health, and logs through APIs.

### Core data flow

Dashboard -> FastAPI route -> engine/service -> database and/or Binance -> JSON response -> dashboard widgets

---

## 6. Backend Startup Flow

Backend entry point: `src/main.py`

What happens on startup:

1. FastAPI app is created.
2. CORS is enabled for local dashboard ports and deployed dashboard URL.
3. All routers are attached.
4. On startup:
   - database tables are created if missing,
   - `LIVE_SCHEDULER_ENABLED` is seeded into `app_settings`,
   - scheduler startup is attempted.

Important startup endpoints:

- `GET /status`
  - basic app status
- `GET /health/db`
  - database health check
- `GET /status/summary`
  - rich runtime summary
- `GET /status/startup-check`
  - startup and connectivity verification

---

## 7. Configuration and Environment Variables

Environment example lives in:

- `bot new backend/.env.example`

Important environment variables:

### Core

- `APP_ENV`
- `DATABASE_URL`
- `DATA_DIR`
- `LOG_LEVEL`

### Auth

- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`

### Exchange

- `BINANCE_TESTNET`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `BINANCE_SPOT_TESTNET_URL`
- `BINANCE_SPOT_MAINNET_URL`

### ML

- `ML_ENABLED`
- `ML_MODEL_DIR`
- `ML_LOOKBACK`
- `ML_AGREE_THRESHOLD`
- `ML_OVERRIDE_THRESHOLD`
- `ML_MODEL_VERSION`

### Trading strategy

- `TRADE_SYMBOL`
- `TRADE_TIMEFRAME`
- `TRADE_LOOKBACK`
- `ADX_THRESHOLD`
- `EMA_FAST`
- `EMA_SLOW`
- `RSI_LEN`
- `RSI_BUY_MIN`
- `RSI_BUY_MAX`
- `RSI_TAKE_PROFIT`
- `BB_LEN`
- `BB_STD`
- `RSI_RANGE_BUY`
- `RSI_RANGE_SELL`

### Risk

- `MAX_RISK_PER_TRADE`
- `STOP_LOSS_ATR_MULT`
- `TAKE_PROFIT_RR`
- `MAX_OPEN_TRADES`
- `COOLDOWN_SECONDS`

### Scheduler

- `LIVE_SCHEDULER_ENABLED`
- `SCHEDULER_INTERVAL_MINUTES`

### Testing

- `RELAXED_ENTRY_FOR_TESTING`

---

## 8. Database Models

Main models are defined in `src/db/models.py`.

### `Order`

Purpose:

- Stores created exchange/paper/backtest orders.

Important fields:

- `mode`
- `symbol`
- `side`
- `order_type`
- `quantity`
- `requested_price`
- `executed_price`
- `status`
- `exchange_order_id`
- `created_at`

### `Trade`

Purpose:

- Stores executed trade fills.

Important fields:

- `mode`
- `symbol`
- `side`
- `quantity`
- `price`
- `fee`
- `fee_asset`
- `ts`

### `Position`

Purpose:

- Tracks open and closed positions.

Important fields:

- `mode`
- `symbol`
- `is_open`
- `entry_price`
- `entry_qty`
- `entry_ts`
- `exit_price`
- `exit_qty`
- `exit_ts`
- `pnl`
- `pnl_pct`

### `EventLog`

Purpose:

- Generic event logging for runtime transparency.

Examples:

- ML events
- exchange events
- order/trade events
- scheduler events
- error logs

### `TradingDecisionLog`

Purpose:

- Full explainability record for every decision cycle.

Important fields:

- `action`
- `confidence`
- `symbol`
- `timeframe`
- `regime`
- `price`
- `adx`
- `ema_fast`
- `ema_slow`
- `rsi`
- `atr`
- `entry_price`
- `stop_loss`
- `take_profit`
- `risk_reward`
- `reason`
- `signals_json`
- `executed`
- `order_id`

This table is the main source for decision transparency on the dashboard.

### Other tables

- `BacktestRun`
- `User`
- `ExchangeConfig`
- `AppSetting`
- `PortfolioSnapshot`

---

## 9. Core Backend Routes

### Exchange routes

File:

- `src/api/routes_exchange.py`

Main responsibilities:

- balances
- ticker price
- klines
- open orders
- all orders
- trades
- live auto-trade
- open/closed positions
- recent exchange logs

Important endpoints:

- `GET /exchange/balances`
- `GET /exchange/balance/{asset}`
- `GET /exchange/ticker/price`
- `GET /exchange/klines`
- `GET /exchange/orders/open`
- `GET /exchange/orders/all`
- `GET /exchange/trades`
- `POST /exchange/auto-trade`
- `GET /exchange/positions/open`
- `GET /exchange/positions/history`
- `GET /exchange/logs/recent`

### Performance routes

File:

- `src/api/routes_status.py`

Important endpoints:

- `GET /exchange/performance`
- `GET /exchange/performance/summary`
- `GET /exchange/performance/ml-vs-rules`
- `GET /exchange/performance/trades/evaluation`

These routes expose analytics, audit, and comparison data.

### Health routes

File:

- `src/api/routes_health.py`

Important endpoints:

- `GET /status/summary`
- `GET /status/startup-check`

These endpoints are used for monitoring and operational confidence.

### Paper trading routes

File:

- `src/api/routes_paper.py`

Examples:

- run paper trade
- get paper price
- list paper positions
- reset wallet
- close position

### Auth routes

File:

- `src/api/routes_auth.py`

Purpose:

- login
- registration
- exchange config access control

### Backtest routes

File:

- `src/api/routes_backtest.py`

Purpose:

- launch backtests
- list runs
- inspect results
- compare validations

---

## 10. Trading Strategy Engine

Main files:

- `src/live/adaptive_strategy.py`
- `src/live/fully_adaptive_strategy.py`
- `src/live/auto_trade_engine.py`

### 10.1 Adaptive strategy

The adaptive strategy classifies the market into:

- `TRENDING`
- `RANGING`
- `UNKNOWN`

It uses indicators like:

- ADX
- EMA
- RSI
- Bollinger Bands
- ATR

### 10.2 Trending logic

Main ideas:

- bullish EMA structure supports BUY
- bearish EMA structure supports SELL
- RSI is used to avoid bad entries and trigger exits

### 10.3 Ranging logic

Main ideas:

- price near lower Bollinger Band plus low RSI can support BUY
- price near upper Bollinger Band plus high RSI can support SELL

### 10.4 Risk levels

For non-HOLD decisions the engine calculates:

- entry price
- stop loss
- take profit
- risk reward

---

## 11. AutoTradeEngine: How It Works

Main file:

- `src/live/auto_trade_engine.py`

This is the most important runtime engine for live decision making.

### Step-by-step decision flow

1. Fetch OHLCV candles from Binance.
2. Build technical indicators using internal indicator functions.
3. Generate rule-based decision from adaptive strategy.
4. Resolve ML model context using:
   - symbol
   - timeframe
   - optional model version
5. If ML is enabled and model exists:
   - load model
   - run prediction
   - compare ML signal with rule signal
6. Combine signals:
   - `rule_only`
   - `combined`
   - `ml_override`
7. Save decision to `TradingDecisionLog`.
8. If action is executable:
   - place order
   - verify exchange order status
   - record local `Order`
   - create or close `Position`
9. Write structured runtime logs to `EventLog`.

### Important internal concepts

#### `TradeSignal`

Represents a signal from:

- rule engine
- ML engine
- combined pipeline
- forced testing override

#### `TradeResult`

Represents execution outcome:

- success/failure
- executed true/false
- signal
- reason
- order id
- price
- quantity
- balance before/after
- position id

### ML alignment

Model resolution uses:

- `ML_MODEL_DIR`
- `symbol`
- `timeframe`
- `ML_MODEL_VERSION`

Each decision stores ML context inside `signals_json`, including:

- model name
- model version
- symbol
- timeframe
- prediction
- confidence
- whether ML changed final action

---

## 12. Technical Indicators

Main file:

- `src/features/indicators.py`

Indicators implemented internally:

- ADX
- Bollinger Bands
- ATR
- EMA
- RSI
- MACD

Why this matters:

- The code no longer depends on `pandas-ta-classic` for core runtime indicators.
- This was changed to avoid dependency conflicts and make installation stable.

There is also:

- `src/features/build_features.py`

This builds ML training/inference features using the internal indicators.

---

## 13. Machine Learning Flow

Main files:

- `src/ml/model_selector.py`
- `src/ml/inference.py`
- `src/ml/features.py`
- `src/ml/dataset.py`
- `src/ml/train.py`

### 13.1 Model selection

`resolve_model_selection()` chooses the most relevant model path.

Priority:

1. model specific to symbol + timeframe
2. version folder
3. base model folder

Example model naming:

- `BTCUSDT_5m`
- `BTCUSDT_1h`
- `ETHUSDT_1h`

### 13.2 Inference

`LstmInfer`:

- loads `model.keras`
- loads scaler data
- loads metadata
- prepares lookback window
- returns:
  - `signal`
  - `confidence`
  - class probabilities

### 13.3 ML + rules combination

The engine supports:

- rule-only mode
- agreement boost mode
- ML override mode

This behavior is controlled by:

- `ML_AGREE_THRESHOLD`
- `ML_OVERRIDE_THRESHOLD`

---

## 14. Scheduler

Main file:

- `src/scheduler/runner.py`

Purpose:

- run auto-trade on an interval
- avoid duplicate overlapping runs
- record portfolio snapshots

How it works:

1. Read enabled flag from DB or env.
2. Start APScheduler job if enabled.
3. Use `_job_lock` so only one cycle runs at a time.
4. Execute auto-trade cycle.
5. Capture portfolio snapshot.

Important operational detail:

- overlapping runs are prevented by a non-blocking lock
- interval is configurable with `SCHEDULER_INTERVAL_MINUTES`

---

## 15. Health and Monitoring

### `GET /status/summary`

Returns:

- app version
- scheduler state
- last decision time
- last successful market fetch
- last successful trade execution
- model loaded or not
- database connectivity
- exchange connectivity

### `GET /status/startup-check`

Returns:

- environment
- app version
- scheduler state
- database connected or not
- exchange connected or not
- dashboard URL
- dashboard reachability
- last timestamps

This is useful for:

- audit review
- operations check
- client confidence

---

## 16. Performance and Audit Endpoints

### `GET /exchange/performance`

Used for:

- total PnL
- drawdown
- win rate
- profit factor
- average win/loss
- decision counts

### `GET /exchange/performance/summary`

Used for quick dashboard cards:

- total PnL
- win rate
- total trades
- last signal

### `GET /exchange/performance/ml-vs-rules`

Used for comparing:

- rule-only trades
- combined trades
- ML override trades
- other trades

Metrics returned:

- total trades
- wins
- losses
- win rate
- false signal rate
- average return per trade
- max drawdown
- sharpe-like ratio
- total PnL
- ML changed action count

### `GET /exchange/performance/trades/evaluation`

Used for trade-by-trade review:

- entry
- exit
- stop loss
- take profit
- entry reason
- ML reason
- exit reason
- realized PnL
- ML effect
- rule signal
- ML signal
- final signal
- model context

---

## 17. Frontend Architecture

Main file:

- `trading-bot-dashboard/src/App.tsx`

### Route structure

Major pages:

- `/`
  - dashboard
- `/backtest/*`
  - backtest views
- `/paper/*`
  - paper trading views
- `/exchange/*`
  - monitoring, orders, trades, buy, auto-trade
- `/logs`
  - logs page
- `/status-summary`
  - status and startup summary
- `/settings`
  - settings page

### Layout

`AppShell` provides:

- sidebar
- topbar
- page title
- subtitle
- action area

### HTTP client

File:

- `src/lib/http.ts`

It provides:

- base API URL
- JSON headers
- auth token injection
- normalized error formatting

### Query layer

Main query hooks:

- `src/apis/exchange/useExchangeQueries.ts`
- `src/apis/api-summary/useStatusSummary.ts`

These hooks use TanStack Query for:

- caching
- refetch
- deduplication
- periodic polling

---

## 18. Frontend Pages and What They Do

### Dashboard page

File:

- `src/pages/Dashboard.tsx`

Shows:

- balance summary
- open positions
- BUY signal rate
- recent errors
- performance card
- system health
- startup check
- rule vs ML comparison
- trade-by-trade evaluation
- crypto prices
- recent decisions
- recent logs

### Exchange monitor

File:

- `src/pages/exchange/ExchangeMonitor.tsx`

Shows:

- live price chart
- symbol and timeframe selector
- orders and trades
- balances
- open positions
- latest decision
- decision chips:
  - rule signal
  - ML signal
  - ML confidence
  - combined signal
  - order id
  - risk reward
  - executed or not

### Status summary page

File:

- `src/pages/summary/StatusSummary.tsx`

Shows:

- app version
- environment
- scheduler state
- model loaded
- database status
- exchange status
- dashboard reachability
- last timestamps

---

## 19. How the Frontend Uses the Backend

Examples:

### Health

- frontend -> `/status/summary`
- frontend -> `/status/startup-check`

### Exchange monitor

- frontend -> `/exchange/ticker/price`
- frontend -> `/exchange/klines`
- frontend -> `/exchange/orders/all`
- frontend -> `/exchange/trades`
- frontend -> `/exchange/decisions/latest`
- frontend -> `/exchange/decisions/recent`

### Performance

- frontend -> `/exchange/performance`
- frontend -> `/exchange/performance/summary`
- frontend -> `/exchange/performance/ml-vs-rules`
- frontend -> `/exchange/performance/trades/evaluation`

---

## 20. Installation and Run Guide

### Backend

Recommended prerequisites:

1. Use Python 3.11.
2. Create a fresh virtual environment.
3. Copy `.env.example` to `.env`.
4. Fill required environment values before starting the server.
5. Install requirements.
6. Run Uvicorn from backend folder.

Required `.env` values before first run:

- `DATABASE_URL`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `BINANCE_TESTNET`
- `JWT_SECRET`

Commands:

```bash
cd "<project-root>"
python3.11 -m venv .venv
source .venv/bin/activate
cp "bot new backend/.env.example" "bot new backend/.env"
# edit "bot new backend/.env" and set real values
pip install -r "bot new backend/requirements.txt"
cd "bot new backend"
python -m uvicorn src.main:app --reload
```

Backend URLs after start:

- API docs: `http://127.0.0.1:8000/docs`
- Basic status: `http://127.0.0.1:8000/status`
- DB health: `http://127.0.0.1:8000/health/db`
- Runtime summary: `http://127.0.0.1:8000/status/summary`
- Startup check: `http://127.0.0.1:8000/status/startup-check`

### Frontend

Commands:

```bash
cd "<project-root>/trading-bot-dashboard"
npm install
npm run dev
```

Frontend URL after start:

- Dashboard: `http://127.0.0.1:5173`

### Production frontend build

```bash
npm run build
```

---

## 21. Testing and Verification

### Backend tests

Current tests verify:

- model selection
- trade evaluation helper logic
- ML/rule bucket metrics helper logic

Command:

```bash
cd "<project-root>"
source .venv/bin/activate
pytest "bot new backend/src/tests/test_model_selector.py" "bot new backend/src/tests/test_routes_status_helpers.py"
```

### Frontend verification

Command:

```bash
cd "<project-root>/trading-bot-dashboard"
npm run build
```

Result at the time of documentation:

- backend tests passed
- frontend build passed

---

## 22. Operational Checklist

Before live usage:

1. Confirm `.env` values are correct.
2. Confirm `DATABASE_URL` works.
3. Confirm Binance testnet keys are valid.
4. Open `/health/db`.
5. Open `/status/summary`.
6. Open `/status/startup-check`.
7. Open dashboard and confirm:
   - balances load
   - price chart loads
   - decisions load
   - logs load
8. If using scheduler:
   - set `LIVE_SCHEDULER_ENABLED=true`
   - verify scheduler state in status summary

---

## 23. Known Limitations

These are important practical notes:

- Full runtime validation still depends on real `.env`, DB, and Binance credentials.
- Large frontend bundle warning may still appear during build, but build succeeds.
- Live behavior quality depends on market conditions and configured risk/strategy values.
- ML usefulness depends on model quality and proper model alignment.

---

## 24. Business-Level Explanation for Client

In simple client language, this system does four big jobs:

1. It watches the market.
2. It decides whether to buy, sell, or hold.
3. It explains why that decision happened.
4. It tracks whether the decision was good or bad.

What makes this system strong is not only order placement. Its real strength is:

- transparency
- monitoring
- decision logging
- performance measurement
- rule vs ML comparison

That means the client can see:

- what the bot decided,
- why it decided it,
- whether ML changed the result,
- whether that helped or hurt performance,
- and whether the system itself is healthy and connected.

---

## 25. Final Summary

This project is now structured as a full-stack trading system with:

- operational backend APIs
- dashboard visibility
- ML-assisted explainable decision making
- health monitoring
- scheduler support
- performance analytics
- trade-by-trade audit support