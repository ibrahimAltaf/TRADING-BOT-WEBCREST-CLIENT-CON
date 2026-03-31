from __future__ import annotations

from typing import Any, Dict, Optional
import os

from fastapi import APIRouter
from sqlalchemy import or_, desc, text

from src.core.config import get_settings
from src.db.session import SessionLocal, engine
from src.db.models import TradingDecisionLog, EventLog, Trade
from src.live.gate_stats import distribution_pct

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/summary")
def status_summary() -> Dict[str, Any]:
    """Return concise runtime health and status information for monitoring.

    Fields returned:
      - app_version
      - scheduler_state
      - last_decision_time
      - last_successful_market_fetch
      - last_successful_trade_execution
      - model_loaded
      - database_connected
      - exchange_connected
    """
    s = get_settings()

    db = SessionLocal()
    try:
        # app version: optional env override
        app_version = os.getenv("APP_VERSION", "1.0")

        # scheduler state: try to import runner.scheduler
        scheduler_state = "unknown"
        try:
            from src.scheduler.runner import scheduler

            job = scheduler.get_job("live_trading_job")
            if scheduler.running and job:
                scheduler_state = "running"
            elif scheduler.running and not job:
                scheduler_state = "running(no-job)"
            else:
                scheduler_state = "stopped"
        except Exception:
            scheduler_state = "unavailable"

        # last decision time
        last_decision = (
            db.query(TradingDecisionLog).order_by(TradingDecisionLog.ts.desc()).first()
        )
        last_decision_ts = last_decision.ts.isoformat() if last_decision else None
        latest_decision = (
            {
                "action": last_decision.action,
                "confidence": (
                    round(last_decision.confidence, 3)
                    if last_decision.confidence is not None
                    else None
                ),
                "reason": last_decision.reason,
                "symbol": last_decision.symbol,
                "timeframe": last_decision.timeframe,
                "executed": bool(last_decision.executed),
                "order_id": last_decision.order_id,
            }
            if last_decision
            else None
        )

        # last successful market fetch: look for EventLog entries that likely indicate fetch/exchange activity
        candidates = ["exchange", "scheduler", "market", "fetch", "klines", "ticker"]
        ev_query = (
            db.query(EventLog)
            .filter(
                or_(
                    EventLog.category.in_(candidates),
                    EventLog.message.ilike("%klines%"),
                    EventLog.message.ilike("%fetch%"),
                    EventLog.message.ilike("%ticker%"),
                )
            )
            .order_by(desc(EventLog.ts))
        )
        ev = ev_query.first()
        last_market_fetch_ts = ev.ts.isoformat() if ev else None

        # last successful trade execution: look at latest Trade.ts
        last_trade = db.query(Trade).order_by(Trade.ts.desc()).first()
        last_trade_ts = last_trade.ts.isoformat() if last_trade else None

        # lightweight activity counters for observability reports
        recent_decisions_count = (
            db.query(TradingDecisionLog)
            .filter(TradingDecisionLog.ts.isnot(None))
            .order_by(TradingDecisionLog.ts.desc())
            .limit(100)
            .count()
        )
        recent_trades_count = (
            db.query(Trade).order_by(Trade.ts.desc()).limit(100).count()
        )

        # model loaded: check ml.inference singleton without importing heavy TF
        model_loaded = False
        try:
            import src.ml.inference as mlinf

            model_loaded = bool(getattr(mlinf, "_cache", {}))
        except Exception:
            model_loaded = False

        # database connected
        db_ok = False
        try:
            with engine.connect() as conn:
                one = conn.execute(text("select 1")).scalar()
            db_ok = bool(one == 1 or one == "1")
        except Exception:
            db_ok = False

        # exchange connected: try a light ticker call using BinanceSpotClient
        exchange_ok = False
        exchange_detail: Optional[str] = None
        try:
            from src.exchange.binance_spot_client import BinanceSpotClient

            try:
                client = BinanceSpotClient()
                # lightweight: ticker for configured trade symbol
                sym = getattr(s, "trade_symbol", "BTCUSDT")
                client.ticker_price(sym)
                exchange_ok = True
            except Exception as exc:
                exchange_ok = False
                exchange_detail = str(exc)
        except Exception as exc:
            exchange_ok = False
            exchange_detail = str(exc)

        return {
            "app_version": app_version,
            "env": s.app_env,
            "binance_testnet": bool(s.binance_testnet),
            "binance_spot_base_url": s.binance_spot_base_url,
            "scheduler_state": scheduler_state,
            "last_decision_time": last_decision_ts,
            "latest_decision": latest_decision,
            "last_successful_market_fetch": last_market_fetch_ts,
            "last_successful_trade_execution": last_trade_ts,
            "model_loaded": model_loaded,
            "database_connected": db_ok,
            "exchange_connected": exchange_ok,
            "exchange_detail": exchange_detail
            or ("ok" if exchange_ok else "unavailable"),
            "observability": {
                "recent_decisions_count": recent_decisions_count,
                "recent_trades_count": recent_trades_count,
            },
        }
    finally:
        db.close()


@router.get("/startup-check")
def startup_check() -> Dict[str, Any]:
    """
    Aggregated startup/health check endpoint for clean boot and audits.

    This is designed to answer:
    - backend alive?
    - port 8000 reachable? (implicit if this route returns)
    - scheduler initialized?
    - database connected?
    - exchange connected?
    - dashboard URL reachable? (optional)
    """
    from src.core.config import get_settings as _get_settings

    s = _get_settings()

    # Re-use the detailed summary for core signals
    summary = status_summary()

    # Optional dashboard URL check
    dashboard_url = os.getenv("DASHBOARD_URL", "").strip()
    dashboard_ok = False
    dashboard_detail: Optional[str] = None

    if dashboard_url:
        try:
            import requests  # type: ignore

            resp = requests.get(dashboard_url, timeout=3)
            dashboard_ok = resp.ok
            dashboard_detail = f"HTTP {resp.status_code}"
        except Exception as exc:
            dashboard_ok = False
            dashboard_detail = str(exc)
    else:
        dashboard_detail = "DASHBOARD_URL not configured"

    return {
        "ok": True,
        "env": s.app_env,
        "binance_testnet": bool(s.binance_testnet),
        "binance_spot_base_url": s.binance_spot_base_url,
        "app_version": summary.get("app_version"),
        "scheduler_state": summary.get("scheduler_state"),
        "database_connected": summary.get("database_connected"),
        "exchange_connected": summary.get("exchange_connected"),
        "dashboard_url": dashboard_url or None,
        "dashboard_connected": dashboard_ok,
        "dashboard_detail": dashboard_detail,
        "last_decision_time": summary.get("last_decision_time"),
        "last_successful_market_fetch": summary.get("last_successful_market_fetch"),
        "last_successful_trade_execution": summary.get(
            "last_successful_trade_execution"
        ),
        "latest_decision": summary.get("latest_decision"),
        "observability": summary.get("observability"),
    }


@router.get("/model-health")
def model_health(load_model: bool = True, smoke: bool = False) -> Dict[str, Any]:
    """Runtime ML resolution + optional load check (for audits).

    Set load_model=false to only resolve paths (lighter; use when polling frequently).
    Set smoke=true to run one inference on recent klines (slower; verifies features + predict).
    """
    s = get_settings()
    out: Dict[str, Any] = {
        "ok": True,
        "ml_enabled": bool(getattr(s, "ml_enabled", False)),
        "ml_model_dir": getattr(s, "ml_model_dir", ""),
        "fully_adaptive_engine": bool(getattr(s, "fully_adaptive_engine", False)),
        "trade_symbol": getattr(s, "trade_symbol", "BTCUSDT"),
        "trade_timeframe": getattr(s, "trade_timeframe", "5m"),
        "model_resolved": None,
        "inferencer_loaded": False,
        "load_model_attempted": False,
        "correct_symbol_match": None,
        "feature_columns_valid": None,
        "inference_working": None,
        "model_loaded": False,
        "error": None,
    }
    if not out["ml_enabled"]:
        out["note"] = "ML disabled in settings (ML_ENABLED=false)"
        return out
    try:
        import os as _os

        from src.ml.model_selector import resolve_model_selection

        version = _os.getenv("ML_MODEL_VERSION", "").strip() or None
        ctx = resolve_model_selection(
            base_model_dir=s.ml_model_dir,
            symbol=s.trade_symbol,
            timeframe=s.trade_timeframe,
            version=version,
        )
        out["model_resolved"] = ctx
        out["correct_symbol_match"] = bool(ctx.get("specific_match"))
        if ctx.get("model_exists") and load_model:
            out["load_model_attempted"] = True
            from src.ml.inference import get_infer

            inf = get_infer(str(ctx["model_dir"]))
            out["inferencer_loaded"] = inf is not None
            out["model_loaded"] = bool(inf is not None)
            if inf is not None and smoke:
                try:
                    import pandas as pd

                    from src.features.indicators import add_all_indicators
                    from src.ml.dataset import append_ml_production_features
                    from src.ml.data_fetch import fetch_public_klines
                    from src.ml.runtime_check import feature_columns_valid, inference_smoke_test

                    lb = int(getattr(s, "ml_lookback", 50) or 50)
                    df = None
                    try:
                        from src.exchange.binance_spot_client import BinanceSpotClient

                        client = BinanceSpotClient()
                        klines = client.klines(
                            symbol=s.trade_symbol,
                            interval=s.trade_timeframe,
                            limit=max(lb + 50, 120),
                        )
                        df = pd.DataFrame(
                            klines,
                            columns=[
                                "open_time",
                                "open",
                                "high",
                                "low",
                                "close",
                                "volume",
                                "close_time",
                                "qav",
                                "num_trades",
                                "taker_base",
                                "taker_quote",
                                "ignore",
                            ],
                        )
                    except Exception:
                        df = None
                    if df is None or len(df) < 60:
                        df = fetch_public_klines(
                            s.trade_symbol, s.trade_timeframe, limit=max(lb + 80, 200)
                        )
                    for col in ["open", "high", "low", "close", "volume"]:
                        df.loc[:, col] = df[col].astype(float)
                    indicator_config = {
                        "ema_fast": s.ema_fast,
                        "ema_slow": s.ema_slow,
                        "rsi_period": s.rsi_len,
                        "adx_period": 14,
                        "bb_period": s.bb_len,
                        "bb_std": s.bb_std,
                        "atr_period": 14,
                    }
                    df = add_all_indicators(df, indicator_config)
                    df = append_ml_production_features(df)
                    df = df.dropna()
                    out["feature_columns_valid"] = feature_columns_valid(df)
                    sm = inference_smoke_test(inf, df)
                    out["inference_working"] = bool(sm.get("inference_working"))
                    out["model_loaded"] = True
                    if sm.get("error"):
                        out["inference_error"] = sm["error"]
                except Exception as ex:
                    out["inference_working"] = False
                    out["inference_error"] = str(ex)[:500]
            elif inf is not None:
                out["inference_working"] = None
                out["note"] = (
                    (out.get("note") or "")
                    + " | set smoke=true for live inference check"
                ).strip(" |")
        elif ctx.get("model_exists") and not load_model:
            out["note"] = "model.keras present; load_model=false (skipped inferencer load)"
        else:
            out["note"] = "No model.keras found for resolved path"
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    out["model_loaded"] = bool(out.get("inferencer_loaded"))
    return out


@router.get("/runtime-paths")
def runtime_paths() -> Dict[str, Any]:
    """Which strategy engine + scheduler + symbols are active."""
    s = get_settings()
    scheduler_state = "unknown"
    try:
        from src.scheduler.runner import scheduler as _sched

        job = _sched.get_job("live_trading_job")
        if _sched.running and job:
            scheduler_state = "running"
        elif _sched.running and not job:
            scheduler_state = "running(no-job)"
        else:
            scheduler_state = "stopped"
    except Exception:
        scheduler_state = "unavailable"

    live_env = os.getenv("LIVE_SCHEDULER_ENABLED", "")
    return {
        "ok": True,
        "strategy_engine": (
            "fully_adaptive" if getattr(s, "fully_adaptive_engine", False) else "adaptive"
        ),
        "scheduler_state": scheduler_state,
        "live_scheduler_env": live_env,
        "trade_symbol": getattr(s, "trade_symbol", "BTCUSDT"),
        "trade_timeframe": getattr(s, "trade_timeframe", "5m"),
        "binance_testnet": bool(s.binance_testnet),
        "binance_spot_base_url": s.binance_spot_base_url,
    }


@router.get("/runtime")
def runtime_status() -> Dict[str, Any]:
    """Alias for GET /status/runtime-paths (spec name: /status/runtime)."""
    return runtime_paths()


@router.get("/gate-stats")
def gate_stats_endpoint() -> Dict[str, Any]:
    """Rolling % of HOLD reasons by kind (in-process since process start)."""
    return {"ok": True, **distribution_pct()}
