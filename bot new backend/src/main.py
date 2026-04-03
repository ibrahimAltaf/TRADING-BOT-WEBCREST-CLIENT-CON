import os
import subprocess
import sys
import threading
from pathlib import Path

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
from src.api.routes_decision import router as decision_router
from src.api.routes_system import router as system_router
from src.api.routes_stats import router as stats_router

try:
    from src.api.routes_auth import router as auth_router

    _auth_available = True
except Exception:
    auth_router = None
    _auth_available = False

app = FastAPI(title="AI Trading System - Phase 1")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _maybe_auto_train_background() -> None:
    """If ML_AUTO_TRAIN_ON_START=true and artifacts missing, run training in a daemon thread."""
    if os.getenv("ML_AUTO_TRAIN_ON_START", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return
    s = get_settings()
    from src.ml.model_verify import check_model_artifacts

    art = check_model_artifacts(Path(s.ml_model_dir))
    if art.get("all_present"):
        print("[STARTUP][ML] artifacts present — skip auto-train")
        return

    root = _repo_root()
    script = root / "scripts" / "train_btc_production.py"
    if not script.is_file():
        print(f"[STARTUP][ML][WARN] auto-train script missing: {script}")
        return

    def _run() -> None:
        env = {**os.environ, "PYTHONPATH": str(root)}
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--limit",
                    "8000",
                    "--epochs",
                    "28",
                ],
                cwd=str(root),
                env=env,
                timeout=7200,
            )
            print("[STARTUP][ML] background training finished")
        except Exception as ex:
            print(f"[STARTUP][ML][ERROR] auto-train failed: {ex}")

    threading.Thread(target=_run, daemon=True).start()
    print(
        "[STARTUP][ML] ML_AUTO_TRAIN_ON_START: background training started "
        "(see logs; inference activates after model files appear)"
    )


def _startup_ml_model_check() -> None:
    """Log explicit ML resolution at boot (no silent misconfiguration)."""
    s = get_settings()
    if not getattr(s, "ml_enabled", False):
        print("[STARTUP][ML] ML_ENABLED=false — inference disabled")
        return
    if not getattr(s, "ml_strict", True):
        print(
            "[STARTUP][ML][WARN] ML_STRICT=false — ML failures may fall back to rules; "
            "set ML_STRICT=true for production"
        )
    try:
        from src.ml.model_selector import resolve_model_selection
        from src.ml.model_verify import check_model_artifacts

        sym_list = list(getattr(s, "supported_trading_symbols", (s.trade_symbol,)))
        all_ok = True
        for sym in sym_list:
            ctx = resolve_model_selection(
                base_model_dir=s.ml_model_dir,
                symbol=sym,
                timeframe=s.trade_timeframe,
                version=os.getenv("ML_MODEL_VERSION", "").strip() or None,
            )
            re_ok = bool(ctx.get("runtime_eligible"))
            art = check_model_artifacts(Path(ctx.get("model_dir", s.ml_model_dir)))
            print(
                f"[STARTUP][ML] symbol={sym} resolved_dir={ctx.get('model_dir')} "
                f"runtime_eligible={re_ok} exact_match_exists={ctx.get('exact_match_exists')} "
                f"artifact_exists={ctx.get('artifact_exists')}"
            )
            print(
                f"[STARTUP][ML] symbol={sym} artifacts model_keras={art['model_keras']} "
                f"scaler_json={art['scaler_json']} meta_json={art['meta_json']}"
            )
            if not re_ok or not art.get("all_present"):
                all_ok = False
                print(
                    f"[STARTUP][ML][ERROR] symbol={sym} missing model artifacts — "
                    "run: PYTHONPATH=. python scripts/train_multi_coin.py "
                    "or train_btc_production.py / set ML_AUTO_TRAIN_ON_START=true"
                )
        if not all_ok:
            _maybe_auto_train_background()
        else:
            print("[STARTUP][ML] all configured symbols: model artifacts OK")
    except Exception as exc:
        print(f"[STARTUP][ML][ERROR] model resolution failed: {exc}")

# Local dev + Vercel preview; VPS HTTP dashboard (port 80) calling API on :8000 is cross-origin — must be listed.
# Note: http://localhost:5173 and http://127.0.0.1:5173 are different browser origins — list both.
# Append CORS_ORIGINS (comma-separated) in .env for extra domains (HTTPS, staging, etc.).
_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://trading-bot-dashboard-delta.vercel.app",
    "http://147.93.96.42",
]
_extra = os.getenv("CORS_ORIGINS", "").strip()
if _extra:
    _origins = _origins + [o.strip() for o in _extra.split(",") if o.strip()]
origins = _origins

# Dev / LAN: phone testing via http://192.168.x.x:5173 — match without listing every IP.
_cors_regex = None
if os.getenv("APP_ENV", "dev").strip().lower() in ("dev", "development"):
    _cors_regex = r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_cors_regex,
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
app.include_router(decision_router)
app.include_router(system_router)
app.include_router(stats_router)
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
        _startup_ml_model_check()
    except Exception as e:
        print(f"[STARTUP] ML model check: {e}")

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
        "binance_spot_base_url": s.binance_spot_base_url,
        "trade_symbol": s.trade_symbol,
        "trade_timeframe": s.trade_timeframe,
        "supported_trading_symbols": list(s.supported_trading_symbols),
        "ml_enabled": bool(s.ml_enabled),
        "ml_strict": bool(s.ml_strict),
        "ml_override_threshold": s.ml_override_threshold,
        "ml_prioritize_threshold": s.ml_prioritize_threshold,
        "rl_hybrid_enabled": bool(s.rl_hybrid_enabled),
    }


@app.get("/status/ml")
def status_ml():
    """Runtime ML flags (verify process actually has ML_ENABLED=true)."""
    s = get_settings()
    return {
        "ok": True,
        "ml_enabled": bool(s.ml_enabled),
        "ml_strict": bool(s.ml_strict),
        "ml_override_threshold": s.ml_override_threshold,
        "ml_prioritize_threshold": s.ml_prioritize_threshold,
        "ml_agree_threshold": s.ml_agree_threshold,
        "ml_min_trade_confidence": s.ml_min_trade_confidence,
        "ml_absolute_min_confidence": s.ml_absolute_min_confidence,
        "ml_model_dir": s.ml_model_dir,
        "supported_trading_symbols": list(s.supported_trading_symbols),
        "rl_hybrid_enabled": s.rl_hybrid_enabled,
        "rl_ppo_model_path": s.rl_ppo_model_path or None,
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
