# Technical Audit Response – AI Trading System

This document addresses the **Technical Audit Report** (1‑Hour Validation + 4‑Hour Deep Diagnostic) and the requested actions from the project owner.

---

## 1. Scheduler concurrency (FIXED)

**Issue:** Logs showed *"maximum number of running instances reached"*, causing skipped cycles and inconsistent timing.

**Change:** A **non-blocking lock** was added in `src/scheduler/runner.py`:

- Only one `live_job` run executes at a time.
- If the previous run is still active when the next trigger fires, the new run **skips immediately** and logs:  
  `Skipping cycle: previous run still in progress. Consider increasing SCHEDULER_INTERVAL_MINUTES if this appears often.`
- This removes reliance on APScheduler’s `max_instances` for the “skipped” message; the job body is simply not started when the lock is held.

**Config:**

- `SCHEDULER_INTERVAL_MINUTES` (default `5`) – interval in minutes. If cycles often run long, set to `10` or `15` in `.env` to reduce overlap.

---

## 2. ML model in the decision pipeline (VERIFIED + LOGGING)

**Issue:** Unclear whether the AI model actually drives decisions.

**Verification:** In `src/live/auto_trade_engine.py` the flow is:

1. **Rule decision** – `AdaptiveStrategy` or `FullyAdaptiveStrategy` produces BUY/SELL/HOLD.
2. **ML (if enabled)** – `_generate_ml_signal()` returns LSTM prediction; `_combine_signals()` applies agree/override thresholds.
3. **Final decision** – Either rule-only, or combined/ML-override when ML is used.

**New audit logging:** Every decision cycle now logs a single line to the **decision** category:

```text
DECISION_PIPELINE | RULE=<BUY|SELL|HOLD> | ML=<BUY|SELL|HOLD|disabled> | FINAL=<BUY|SELL|HOLD> | SOURCE=<rule_only|combined|ml_override|rule_only_ml_disabled>
```

- **ML=disabled** – `ML_ENABLED` is false or ML failed; only rule is used.
- **SOURCE=rule_only_ml_disabled** – ML is off.
- **SOURCE=combined** – Rule and ML agreed; confidence boosted.
- **SOURCE=ml_override** – ML overrode the rule (high confidence).

**How to confirm ML is used:**

1. Set in `.env`: `ML_ENABLED=true` and ensure `ML_MODEL_DIR` points to a valid model (e.g. `models/lstm_v1/SOLUSDT_15m` or the symbol/timeframe you use).
2. In logs or `/exchange/logs/recent`, look for:
   - `ML prediction: signal=... confidence=...`
   - `DECISION_PIPELINE | ... | ML=BUY|SELL|HOLD | ... | SOURCE=combined` or `SOURCE=ml_override`

**Note:** With ~48% validation accuracy, the model rarely reaches the override threshold, so most decisions will stay rule-based until the model is improved.

---

## 3. Entry conditions for testing (RELAXED MODE)

**Issue:** Almost all decisions were HOLD; no trades to evaluate.

**Change:** Optional **relaxed entry** mode for validation only:

- **Env:** `RELAXED_ENTRY_FOR_TESTING=true` (default `false`).
- **Effect:**
  - **Trending:** Wider RSI buy band (e.g. 40–75) and higher RSI take-profit (78).
  - **Ranging:** Wider RSI range (buy ≤40, sell ≥70) and band distance up to 5% (vs 3%).

Use this only on **testnet/demo** to generate more BUY/SELL signals during tests. Turn **off** for production.

---

## 4. Backtest engine – ML imports (FIXED)

**Issue:** When `ML_ENABLED=true`, backtest could fail due to missing imports.

**Change:** In `src/backtest/engine.py` the following imports were added:

- `from src.ml.inference import get_infer`
- `from src.ml.ensemble import combine`

Backtest with ML enabled can now run without import errors.

---

## 5. Performance metrics (ALREADY AVAILABLE)

The report asked for profit, drawdown, win rate. These are already exposed:

- **API:** `GET /exchange/performance` and `GET /exchange/performance/summary` (see `src/api/routes_status.py`).
- **Metrics:** total PnL, win rate, profit factor, max drawdown, avg win/loss, decision counts.

The dashboard can call these endpoints to show performance.

---

## 6. Reproducing the diagnostic

1. **Env:** Use the provided testnet keys and set:
   - `BINANCE_TESTNET=true`
   - `LIVE_SCHEDULER_ENABLED=true`
   - Optionally `RELAXED_ENTRY_FOR_TESTING=true` for more signals
   - Optionally `ML_ENABLED=true` and correct `ML_MODEL_DIR` to verify ML path
2. **Run backend**, then run the 1‑hour and 4‑hour diagnostic scripts.
3. **Check logs** for:
   - `DECISION_PIPELINE | RULE=... | ML=... | FINAL=... | SOURCE=...`
   - Any `Skipping cycle: previous run still in progress` (if so, increase `SCHEDULER_INTERVAL_MINUTES`).

---

## 7. Summary of files changed

| Area              | File(s) |
|-------------------|--------|
| Scheduler         | `src/scheduler/runner.py` – lock + interval env |
| Decision logging  | `src/live/auto_trade_engine.py` – DECISION_PIPELINE + rule/ML vars |
| Relaxed entry     | `src/core/config.py`, `src/live/auto_trade_engine.py`, `src/live/adaptive_strategy.py` |
| Backtest ML       | `src/backtest/engine.py` – `get_infer`, `combine` imports |
| Documentation     | `docs/AUDIT-RESPONSE.md` (this file) |

---

## 8. Next steps (recommendations)

1. **Model:** Improve LSTM (or consider XGBoost for tabular data) – more/better features, labeling, and validation so accuracy is clearly above random.
2. **24‑hour test:** After deploying these fixes, run a 24‑hour diagnostic and measure trade frequency, win rate, profit factor, and drawdown via `/exchange/performance`.
3. **Dashboard:** Wire dashboard to `GET /exchange/performance` and `GET /exchange/performance/summary` for live metrics.

If you want, we can next tighten the strategy logic or add more logging for specific scenarios.
