from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os
import threading

from src.exchange.binance_spot_client import BinanceSpotClient
from src.risk.rules import RiskConfig
from src.live.auto_trade_engine import AutoTradeEngine
from src.live.portfolio import capture_portfolio_snapshot
from src.db.session import SessionLocal
from src.core.config import get_settings

scheduler = BackgroundScheduler(timezone="UTC")
client = BinanceSpotClient()

# Prevent overlapping runs: if previous job still running, skip this cycle instead of
# letting APScheduler log "maximum number of running instances reached".
_job_lock = threading.Lock()

# Interval in minutes (env SCHEDULER_INTERVAL_MINUTES, default 5). Increase to 10–15
# if each cycle often takes longer than the interval.
def _scheduler_interval_minutes() -> int:
    try:
        v = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "5").strip())
        return max(1, min(60, v))
    except ValueError:
        return 5


def _is_scheduler_enabled() -> bool:
    """
    Read the live-scheduler flag from the DB (app_settings table).
    Falls back to the LIVE_SCHEDULER_ENABLED env var if the row
    doesn't exist yet (first boot before DB seed).
    """
    try:
        from src.db.models import AppSetting

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="LIVE_SCHEDULER_ENABLED").first()
            if row is not None:
                return row.value.lower() == "true"
        finally:
            db.close()
    except Exception:
        pass  # table may not exist yet
    return os.getenv("LIVE_SCHEDULER_ENABLED", "false").lower() == "true"


def live_job():
    """
    Execute auto-trade using AutoTradeEngine.
    Uses a non-blocking lock so only one instance runs at a time; if the previous
    run is still active, this cycle is skipped (no APScheduler 'max instances' skip).
    """
    if not _job_lock.acquire(blocking=False):
        print(
            f"[SCHEDULER][{datetime.utcnow()}] Skipping cycle: previous run still in progress. "
            "Consider increasing SCHEDULER_INTERVAL_MINUTES if this appears often."
        )
        return
    try:
        _run_live_job()
    finally:
        _job_lock.release()


def _run_live_job():
    """Inner live job: holds _job_lock already — one independent cycle per symbol."""
    db = SessionLocal()
    try:
        settings = get_settings()
        symbols = list(settings.supported_trading_symbols)
        timeframe = settings.trade_timeframe

        risk = RiskConfig(
            max_position_pct=0.1,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            fee_pct=0.001,
        )

        engine = AutoTradeEngine(db=db, client=client, risk_config=risk)

        b1 = client.balances_map()
        usdt_before = float(b1.get("USDT", "0"))

        any_executed = False
        for symbol in symbols:
            result = engine.execute_auto_trade(
                symbol=symbol,
                timeframe=timeframe,
                risk_pct=risk.max_position_pct,
            )
            ts = datetime.utcnow()
            if result.executed:
                any_executed = True
                print(
                    f"[SCHEDULER][{ts}] {symbol} orderId={result.order_id} "
                    f"status={result.exchange_status} price={result.price:.4f}"
                )
            else:
                print(
                    f"[SCHEDULER][{ts}] {symbol} signal={result.signal} "
                    f"reason={result.reason}"
                )

        b2 = client.balances_map()
        usdt_after = float(b2.get("USDT", "0"))
        if any_executed:
            print(
                f"[SCHEDULER][{datetime.utcnow()}] portfolio USDT {usdt_before:.2f}->{usdt_after:.2f}"
            )

        try:
            capture_portfolio_snapshot(db=db, client=client, source="scheduler")
        except Exception as snap_err:
            print(f"[SCHEDULER][{datetime.utcnow()}] snapshot error: {snap_err}")

    except Exception as e:
        print(f"[SCHEDULER][{datetime.utcnow()}] ERROR: {e}")
    finally:
        db.close()


def start_scheduler():
    if not _is_scheduler_enabled():
        print("[SCHEDULER] live disabled (LIVE_SCHEDULER_ENABLED=false)")
        return

    if scheduler.get_job("live_trading_job"):
        return

    interval_min = _scheduler_interval_minutes()
    scheduler.add_job(
        live_job,
        trigger=IntervalTrigger(minutes=interval_min),
        id="live_trading_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,  # allow late start so we don't drop cycles when busy
    )
    scheduler.start()
    print(f"[SCHEDULER] live started (interval={interval_min} min)")


def stop_scheduler():
    if scheduler.get_job("live_trading_job"):
        scheduler.remove_job("live_trading_job")

    if scheduler.running:
        scheduler.shutdown(wait=False)

    print("[SCHEDULER] live stopped")
