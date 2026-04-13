# AI Trading System — WebCrest

Production-oriented monorepo for an **AI-assisted cryptocurrency trading platform**: a **FastAPI** backend combining rule-based strategy, **LSTM** machine learning, optional **RL** layers, **Binance Spot** integration, **PostgreSQL**, a live **multi-symbol scheduler**, and a **React (Vite)** dashboard for monitoring and audits.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Key improvements](#2-key-improvements)
3. [AI decision flow](#3-ai-decision-flow)
4. [API endpoints](#4-api-endpoints)
5. [Frontend dashboard](#5-frontend-dashboard)
6. [Testing and validation](#6-testing-and-validation)
7. [Runtime validation notes](#7-runtime-validation-notes)
8. [Production readiness](#8-production-readiness)
9. [How to run the project](#9-how-to-run-the-project)
10. [Final summary](#10-final-summary)
11. [Repository layout and docs](#11-repository-layout-and-docs)

---

## 1. Project overview

**What the system does**

- Ingests market data (Binance REST / klines), computes technical indicators and ML features, and produces **BUY / SELL / HOLD** decisions per configured symbol and timeframe.
- **Fuses** adaptive rule logic with **LSTM** softmax outputs under configurable thresholds; optional portfolio / hybrid risk caps when enabled.
- Persists decisions, positions, orders, and structured **signals** for explainability and compliance-style review.
- Runs an optional **scheduler** that executes trading cycles across **multiple symbols** (e.g. BTC, ETH, SOL) on a fixed interval.

**Technologies**

| Layer    | Stack                                                                                    |
| -------- | ---------------------------------------------------------------------------------------- |
| API      | Python 3, **FastAPI**, Uvicorn, SQLAlchemy, Pydantic                                     |
| ML       | TensorFlow/Keras (`model.keras`), StandardScaler (`scaler.json`), metadata (`meta.json`) |
| Data     | **PostgreSQL**                                                                           |
| Exchange | Binance Spot (testnet or live), signed requests with clock sync                          |
| UI       | **React 19**, **Vite**, TypeScript, TanStack Query, Tailwind                             |

---

## 2. Key improvements

**Strict ML enforcement (`ML_STRICT`)**

- When enabled, the live engine does **not** silently fall back to rules-only trading if ML is required but missing, mis-resolved, or failing in a way that would hide risk.
- Failures surface as explicit outcomes (e.g. `ml_strict_failure`) and structured logs instead of quiet degradation.

**Runtime eligibility (exact model matching)**

- Models resolve to **exact** directories: `ML_MODEL_DIR/<SYMBOL>_<TIMEFRAME>/` (or versioned layout), each containing **`model.keras`**, **`scaler.json`**, **`meta.json`**.
- No permissive pick of a wrong folder; diagnostics report `runtime_eligible`, `exact_match_exists`, and `artifact_exists`.

**Multi-symbol scheduler**

- Configurable list of symbols (default **BTCUSDT**, **ETHUSDT**, **SOLUSDT**) shares one **`TRADE_TIMEFRAME`** from settings; each cycle runs the engine per symbol with its own resolved model path.

**Risk management and position sizing**

- Adaptive strategy and engine apply stops, take-profit, risk-reward, cooldowns, and caps driven by environment and `RiskConfig` (see `src/risk/` and live engine).

**Exception auditing (`engine_exception`)**

- Severe pipeline failures can be recorded with **`final_source: engine_exception`** so dashboards and `/exchange/decisions/recent` expose failures alongside normal decisions.

**Observability (AI metrics, entropy, logs)**

- **`/exchange/performance/ai-observability`** aggregates ML usage rates, runtime posture (including `ml_strict_failure` counts), **Shannon entropy** over `final_source`, and rule/ML/final pattern diversity from recent `TradingDecisionLog` rows.

---

## 3. AI decision flow

**How ML is used**

- Indicators and features feed an LSTM inferencer for the **resolved** model directory; softmax yields SELL/HOLD/BUY-style probabilities and a **confidence** (argmax probability).
- The engine merges **rule_signal** with **ml_signal** using thresholds: agree, override, prioritize, hold-breakout, and moderate influence (see `src/live/auto_trade_engine.py`, `src/live/cycle_decision.py`).

**When ML is valid**

- `runtime_eligible` is true, inference succeeds, and gates pass: decisions may be labeled with sources such as **`combined`**, **`ml_override`**, **`ml_prioritize`**, **`rule_only`**, or **`ml_hold_breakout`** depending on configuration and confidence.

**When ML is missing or fails under `ML_STRICT`**

- Resolution fails (no exact folder / incomplete artifacts) or inference aborts as configured: the cycle can end with **`ml_strict_failure`** — the trading step is aborted for that symbol rather than silently ignoring ML.

**Meaning of key labels**

| Label                 | Meaning                                                                                                                                                                             |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ml_override**       | ML direction and confidence exceed **`ML_OVERRIDE_THRESHOLD`** so ML drives the fused outcome when rules would differ (per engine logic).                                           |
| **ml_prioritize**     | Very high ML confidence (≥ **`ML_PRIORITIZE_THRESHOLD`**) takes precedence in the fusion path.                                                                                      |
| **ml_strict_failure** | Strict ML path required ML but model path invalid, artifacts missing, or ML pipeline failed in a way that triggers abort — **no silent rule-only fill-in** when strict rules apply. |
| **engine_exception**  | Unexpected engine-level failure; audited on the decision/log path for post-mortems.                                                                                                 |

---

## 4. API endpoints

Base URL example: `http://127.0.0.1:8000` (local). All paths are relative to that origin.

**`GET /exchange/performance/ai-observability`**

- Query params: `symbol` (optional filter), `limit` (capped, default 5000).
- Returns JSON with **`ml_usage`** (percent of rows with ML signal/confidence), **`runtime_posture`** (counts by runtime mode, degraded cycles, **`ml_strict_failure_cycles`**), **`decision_diversity`** (distinct rule/ML/final patterns, top patterns, **`final_source_entropy_bits`**), and **`final_source_counts`**.

**`GET /exchange/decisions/recent`**

- Query params: `symbol`, `action`, `limit`.
- Returns recent **`TradingDecisionLog`** rows with transparency fields: **`rule_signal`**, **`ml_signal`**, **`ml_confidence`**, **`combined_signal`**, **`override_reason`**, **`final_action`**, indicators, risk block, **`final_source`**, **`cycle_debug`**, execution flags.

**`GET /exchange/proof`**

- Query param: `symbol` (optional; defaults to configured trade symbol).
- **Unified audit snapshot**: balances, recent decisions, latest decision, PnL/summary slices, orders, positions, recent logs. Subsections are isolated — **`section_errors`** records which subsection failed without invalidating the whole payload.

**`GET /status/model-health/symbols`**

- Query param: `load_model` (optional heavier load per symbol).
- Per-symbol ML resolution: **`model_dir`**, **`exact_match_exists`**, **`runtime_eligible`**, **`reason`**, optional **`runtime_health`** when loading.

Additional useful routes: **`GET /status`**, **`GET /status/ml`**, **`GET /status/summary`**, **`GET /status/model-health`**, **`GET /health/db`**, **`GET /docs`** (OpenAPI).

---

## 5. Frontend dashboard

**Stack:** React 19, Vite, TypeScript, TanStack Query, Tailwind (see `trading-bot-dashboard/`).

**Observability panel**

- Consumes **`/exchange/performance/ai-observability`** (e.g. from `ExchangeMonitor`, `StatusSummary`) to show ML usage, strict-failure counts, and runtime posture.

**Decision table**

- Uses **`/exchange/decisions/recent`** (and related APIs) to show per-row explainability: rules vs ML, confidence, **`final_source`**, and execution.

**Logs view**

- Event and system logs via logs routes and proof-style sections where applicable.

**Symbol switching**

- Dashboard requests pass **`symbol=BTCUSDT`**, **`ETHUSDT`**, **`SOLUSDT`** where supported so operators can isolate behavior per asset.

**Dev proxy:** Vite proxies `/api` to the backend — configure **`VITE_API_BASE_URL`** for production builds pointing at the public API.

---

## 6. Testing and validation

**Automated tests**

- **`pytest`** suite under `bot new backend/src/tests`: **56** collected tests covering API contracts, model selection, symbols, ML fusion paths, cycle decision regression, JSON safety, position sizing, routes helpers, and more.
- Run: `cd "bot new backend"` then `python -m pytest src/tests -q`.

**Contract testing**

- `src/tests/test_api_exchange_contracts.py` validates shapes and behaviors for **`/exchange/decisions/recent`** and **`/exchange/performance/ai-observability`** (including **`final_source`** and **`ml_strict_failure`** handling).

**Multi-cycle and operational validation**

- Scheduler-driven **multi-cycle** runs (e.g. **8+** live intervals) are used in staging or VPS validation to confirm strict ML behavior, logging, and observability under repeated ticks — not all captured in unit tests alone.

**Frontend**

- Production bundle: `cd trading-bot-dashboard && npm install && npm run build` (TypeScript check + Vite build). **`npm run dev`** for local development.

---

## 7. Runtime validation notes

**Binance timestamp (-1021)**

- Signed requests use server time alignment: **`GET /api/v3/time`** offset is applied and **`recvWindow`** is set so clock skew does not trigger **-1021** timestamp errors (see `src/exchange/binance_spot_client.py`).

**ML usage metrics**

- **`ai-observability`** improves visibility into how often ML fields appear in stored signals and how often strict failures occur — useful for tuning thresholds after deployment.

**Live observation of `ml_override` / `ml_prioritize`**

- These labels appear when market conditions and confidence cross configured bars. **Live cycles** (and sufficient decision volume) are needed to see them regularly in **`final_source_counts`** and decision rows.

---

## 8. Production readiness

**From code and tests**

- The architecture supports **strict**, **auditable**, **multi-symbol** operation with comprehensive API tests and contract coverage.

**Operational requirements before relying on production capital**

| Requirement             | Notes                                                                                                                                           |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Correct system time** | VPS/host NTP; avoids Binance signed-request failures.                                                                                           |
| **Valid ML models**     | Per-symbol **`SYMBOL_TIMEFRAME`** folders with all three artifacts; **`TRADE_TIMEFRAME`** must match on-disk layout for every scheduled symbol. |
| **Live validation**     | Smoke **`/status`**, **`/health/db`**, **`/status/model-health`**, and dashboard panels on the target environment.                              |
| **Secrets and DB**      | Strong **`JWT_SECRET`**, valid **`DATABASE_URL`**, non-committed **`.env`**.                                                                    |
| **Process model**       | Single Uvicorn (or systemd) listener per port; avoid duplicate bind races on restart.                                                           |

The system is **ready for production testing** when the above are satisfied; financial risk remains the operator’s responsibility.

---

## 9. How to run the project

### One-click setup (Windows)

For a fully automated setup and launch of both backend and frontend, use the provided **start.cmd** script:

```cmd
start.cmd
```

This script will:

- Set up the backend Python virtual environment (if missing)
- Install backend dependencies
- Install frontend dependencies (if missing)
- Start the backend (Uvicorn/FastAPI) and frontend (Vite/React) servers in separate terminals

> **Note:** Edit your environment variables (e.g. `.env` for backend, `production.env.example` for frontend) as needed before running in production.

---

### Manual steps (advanced)

**Backend**

```bash
cd "bot new backend"
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-ml.txt
cp .env.example .env
# Edit .env: DATABASE_URL, Binance keys, TRADE_*, ML_*, JWT_*, etc.

python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend**

```bash
cd trading-bot-dashboard
npm install
npm run dev
# Production build:
npm run build
```

**Quick health checks**

```bash
curl -s http://127.0.0.1:8000/status
curl -s http://127.0.0.1:8000/health/db
```

---

## 10. Final summary

- The backend behaves as a **strict, AI-aware trading engine**: rules plus LSTM fusion, explicit **`final_source`** labeling, and **no silent ML bypass** when **`ML_STRICT`** is on.
- **Observability** (AI observability endpoint, entropy, decision transparency) and **audit** endpoints (**`/exchange/proof`**) support client and operator review.
- **Multi-symbol** scheduling and per-symbol model resolution make the stack suitable for **BTC / ETH / SOL** (or other configured pairs) from one deployment.
- After automated tests and environment validation, the project is positioned for **production testing** under real keys, real models, and monitored infrastructure.

---

## 11. Repository layout and docs

| Path                      | Role                                                            |
| ------------------------- | --------------------------------------------------------------- |
| `bot new backend/`        | FastAPI app (`src/main.py`), ML, live engine, scheduler, tests  |
| `trading-bot-dashboard/`  | React dashboard                                                 |
| `bot new backend/docs/`   | VPS deployment guides (`VPS-DEPLOY.md`, `VPS-VAR-WWW.md`, etc.) |
| `bot new backend/models/` | Trained artifacts per `SYMBOL_TIMEFRAME`                        |

---

## One-click project setup script: `start.cmd`

For convenience, a Windows batch script is provided for one-click setup and launch. Here is what it does:

```batch
@echo off
setlocal

echo ==========================================
echo Setting up backend virtual environment...
echo ==========================================

cd /d "%~dp0bot new backend"

IF NOT EXIST ".venv" (
	echo Creating .venv...
	python -m venv .venv
)

echo Activating .venv and installing backend dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

echo ==========================================
echo Installing frontend dependencies...
echo ==========================================

cd /d "%~dp0trading-bot-dashboard"

IF NOT EXIST "node_modules" (
	call npm install
)

echo ==========================================
echo Starting backend...
echo ==========================================

start "Backend Server" cmd /k "cd /d ""%~dp0bot new backend"" && call .venv\Scripts\activate.bat && uvicorn src.main:app --reload"

echo ==========================================
echo Starting frontend...
echo ==========================================

start "Frontend Server" cmd /k "cd /d ""%~dp0trading-bot-dashboard"" && npm run dev"

echo Both servers started 🚀
pause
```

This script is located at the root of the repository as `start.cmd`.

**Deploy note:** On Linux servers, prefer a path **without spaces** (e.g. symlink `bot-new-backend`) for systemd and tooling.

**Docker:** `bot new backend/docker-compose.yml` with `.env.production` where applicable.

---

## License

Private / client project — adjust as needed.
