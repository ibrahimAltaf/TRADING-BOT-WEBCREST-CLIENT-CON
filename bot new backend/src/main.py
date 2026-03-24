import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.core.config import get_settings
from src.db.session import engine
from src.api.routes_exchange import router as exchange_router
from src.api.routes_backtest import router as backtest_router
from src.api.routes_logs import router as logs_router
from src.api.routes_paper import router as paper_router
from src.api.routes_live import router as live_router
from src.scheduler.runner import start_scheduler
from src.api.routes_settings import router as settings_router
from src.api.routes_demo import router as demo_router
from src.api.routes_status import router as status_router
from src.api.routes_health import router as health_router
from src.api.routes_health import status_summary as status_summary_handler
from src.api.routes_strategy import router as strategy_router

try:
    from src.api.routes_auth import router as auth_router

    _auth_available = True
except Exception:
    auth_router = None
    _auth_available = False

app = FastAPI(title="AI Trading System - Phase 1")

# Local dev + Vercel preview; VPS HTTP dashboard (port 80) calling API on :8000 is cross-origin — must be listed.
# Append CORS_ORIGINS (comma-separated) in .env for extra domains (HTTPS, staging, etc.).
_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "https://trading-bot-dashboard-delta.vercel.app",
    "http://147.93.96.42",
]
_extra = os.getenv("CORS_ORIGINS", "").strip()
if _extra:
    _origins = _origins + [o.strip() for o in _extra.split(",") if o.strip()]
origins = _origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(backtest_router)
app.include_router(logs_router)
app.include_router(paper_router)
app.include_router(exchange_router)
app.include_router(live_router)
app.include_router(settings_router)
app.include_router(demo_router)
app.include_router(status_router)
app.include_router(health_router)
app.include_router(strategy_router, prefix="/strategy")

if _auth_available and auth_router is not None:
    app.include_router(auth_router)


@app.on_event("startup")
def startup():
    try:
        from src.db.base import Base
        from src.db.models import AppSetting, User, ExchangeConfig  # noqa: F401

        Base.metadata.create_all(bind=engine)

        from src.db.session import SessionLocal
        import os

        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="LIVE_SCHEDULER_ENABLED").first()
            if row is None:
                env_val = os.getenv("LIVE_SCHEDULER_ENABLED", "false").lower()
                db.add(AppSetting(key="LIVE_SCHEDULER_ENABLED", value=env_val))
                db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[STARTUP] settings seed error: {e}")

    try:
        start_scheduler()
    except Exception as e:
        print(f"[SCHEDULER] not started: {e}")


@app.get("/status")
def status():
    s = get_settings()
    return {
        "ok": True,
        "phase": 1,
        "env": s.app_env,
        "binance_testnet": s.binance_testnet,
    }


@app.get("/status-summary")
def status_summary_alias():
    """Same payload as GET /status/summary — for audits/tools that expect kebab-case."""
    return status_summary_handler()


@app.get("/health/db")
def db_health():
    try:
        with engine.connect() as c:
            one = c.execute(text("select 1")).scalar()
        return {"db": "ok", "select_1": one}
    except OperationalError as e:
        return {"db": "error", "detail": str(e.orig)}
