from __future__ import annotations

from typing import Any, Dict, Optional
import os

from fastapi import APIRouter
from sqlalchemy import or_, desc, text

from src.core.config import get_settings
from src.db.session import SessionLocal, engine
from src.db.models import TradingDecisionLog, EventLog, Trade

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
            "scheduler_state": scheduler_state,
            "last_decision_time": last_decision_ts,
            "last_successful_market_fetch": last_market_fetch_ts,
            "last_successful_trade_execution": last_trade_ts,
            "model_loaded": model_loaded,
            "database_connected": db_ok,
            "exchange_connected": exchange_ok,
            "exchange_detail": exchange_detail
            or ("ok" if exchange_ok else "unavailable"),
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
    }
