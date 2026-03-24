import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env from project root
load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    data_dir: str
    log_level: str
    binance_testnet: bool
    binance_api_key: str
    binance_api_secret: str
    binance_spot_base_url: str
    # ML settings
    ml_enabled: bool
    ml_model_dir: str
    ml_lookback: int
    ml_agree_threshold: float
    ml_override_threshold: float
    # Adaptive Trading Strategy Parameters
    # General
    trade_symbol: str
    trade_timeframe: str
    trade_lookback: int
    # Regime Detection
    adx_threshold: float
    atr_vol_threshold: float
    # Trending Rules
    ema_fast: int
    ema_slow: int
    rsi_len: int
    rsi_buy_min: float
    rsi_buy_max: float
    rsi_take_profit: float
    # Ranging Rules
    bb_len: int
    bb_std: float
    rsi_range_buy: float
    rsi_range_sell: float
    # Risk Management
    max_risk_per_trade: float
    stop_loss_atr_mult: float
    take_profit_rr: float
    max_open_trades: int
    cooldown_seconds: int
    # Order Execution Mode
    demo_open_only: bool
    demo_fill_mode: bool
    # Engine selection
    fully_adaptive_engine: bool
    # Binance Demo Mode
    binance_demo_api_key: str
    binance_demo_api_secret: str
    binance_demo_base_url: str
    # Testing: relax entry conditions to allow more BUY/SELL signals (for validation only)
    relaxed_entry_for_testing: bool
    # Auth (JWT) for login / exchange config
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y")


def _env_int(name: str, default: str) -> int:
    v = os.getenv(name, default).strip()
    try:
        return int(v)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer. Got: {v!r}")


def _env_float(name: str, default: str) -> float:
    v = os.getenv(name, default).strip()
    try:
        return float(v)
    except ValueError:
        raise RuntimeError(f"{name} must be a float. Got: {v!r}")


def get_settings() -> Settings:
    # Required
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing in .env")

    # Optional / defaulted
    app_env = os.getenv("APP_ENV", "dev").strip()

    # Use relative path from project root
    data_dir = os.getenv("DATA_DIR", "./data").strip()
    data_path = Path(data_dir).resolve()
    data_path.mkdir(parents=True, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").strip()
    binance_testnet = _env_bool("BINANCE_TESTNET", "true")
    binance_api_key = os.getenv("BINANCE_API_KEY", "").strip()
    binance_api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

    # default base URLs
    spot_mainnet = os.getenv(
        "BINANCE_SPOT_MAINNET_URL", "https://api.binance.com"
    ).strip()
    spot_testnet = os.getenv(
        "BINANCE_SPOT_TESTNET_URL", "https://testnet.binance.vision"
    ).strip()
    binance_spot_base_url = spot_testnet if binance_testnet else spot_mainnet

    # ===== ML (Phase-1 included, feature-flagged) =====
    ml_enabled = _env_bool("ML_ENABLED", "false")
    ml_model_dir = os.getenv("ML_MODEL_DIR", "models/lstm_v1").strip()
    ml_lookback = _env_int("ML_LOOKBACK", "100")
    ml_agree_threshold = _env_float("ML_AGREE_THRESHOLD", "0.70")
    ml_override_threshold = _env_float("ML_OVERRIDE_THRESHOLD", "0.85")

    # Resolve ML model dir relative to project root
    ml_model_path = Path(ml_model_dir).resolve()

    # ===== Adaptive Trading Strategy Parameters =====
    # General
    trade_symbol = os.getenv("TRADE_SYMBOL", "BTCUSDT").strip()
    trade_timeframe = os.getenv("TRADE_TIMEFRAME", "5m").strip()
    trade_lookback = _env_int("TRADE_LOOKBACK", "500")

    # Regime Detection
    adx_threshold = _env_float("ADX_THRESHOLD", "25.0")
    atr_vol_threshold = _env_float("ATR_VOL_THRESHOLD", "2.0")

    # Trending Rules
    ema_fast = _env_int("EMA_FAST", "20")
    ema_slow = _env_int("EMA_SLOW", "50")
    rsi_len = _env_int("RSI_LEN", "14")
    rsi_buy_min = _env_float("RSI_BUY_MIN", "45.0")
    rsi_buy_max = _env_float("RSI_BUY_MAX", "70.0")
    rsi_take_profit = _env_float("RSI_TAKE_PROFIT", "75.0")

    # Ranging Rules
    bb_len = _env_int("BB_LEN", "20")
    bb_std = _env_float("BB_STD", "2.0")
    rsi_range_buy = _env_float("RSI_RANGE_BUY", "35.0")
    rsi_range_sell = _env_float("RSI_RANGE_SELL", "65.0")

    # Risk Management
    max_risk_per_trade = _env_float("MAX_RISK_PER_TRADE", "0.01")  # 1%
    stop_loss_atr_mult = _env_float("STOP_LOSS_ATR_MULT", "2.0")
    take_profit_rr = _env_float("TAKE_PROFIT_RR", "2.0")  # Risk:Reward 1:2
    max_open_trades = _env_int("MAX_OPEN_TRADES", "1")
    cooldown_seconds = _env_int("COOLDOWN_SECONDS", "60")

    # Order Execution Mode
    demo_open_only = _env_bool("DEMO_OPEN_ONLY", "false")
    demo_fill_mode = _env_bool("DEMO_FILL_MODE", "true")
    # Engine selection
    fully_adaptive_engine = _env_bool("FULLY_ADAPTIVE_ENGINE", "false")

    # Binance Demo Mode credentials / base URL
    binance_demo_api_key = os.getenv("BINANCE_DEMO_API_KEY", "").strip()
    binance_demo_api_secret = os.getenv("BINANCE_DEMO_API_SECRET", "").strip()
    binance_demo_base_url = os.getenv(
        "BINANCE_DEMO_BASE_URL", "https://demo-api.binance.com"
    ).strip()

    relaxed_entry_for_testing = _env_bool("RELAXED_ENTRY_FOR_TESTING", "false")

    jwt_secret = os.getenv("JWT_SECRET", "change-me-in-production").strip()
    jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256").strip()
    jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days default

    return Settings(
        app_env=app_env,
        database_url=database_url,
        data_dir=str(data_path),
        log_level=log_level,
        binance_testnet=binance_testnet,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        binance_spot_base_url=binance_spot_base_url,
        # ML
        ml_enabled=ml_enabled,
        ml_model_dir=str(ml_model_path),
        ml_lookback=ml_lookback,
        ml_agree_threshold=ml_agree_threshold,
        ml_override_threshold=ml_override_threshold,
        # Adaptive Trading
        trade_symbol=trade_symbol,
        trade_timeframe=trade_timeframe,
        trade_lookback=trade_lookback,
        adx_threshold=adx_threshold,
        atr_vol_threshold=atr_vol_threshold,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_len=rsi_len,
        rsi_buy_min=rsi_buy_min,
        rsi_buy_max=rsi_buy_max,
        rsi_take_profit=rsi_take_profit,
        bb_len=bb_len,
        bb_std=bb_std,
        rsi_range_buy=rsi_range_buy,
        rsi_range_sell=rsi_range_sell,
        max_risk_per_trade=max_risk_per_trade,
        stop_loss_atr_mult=stop_loss_atr_mult,
        take_profit_rr=take_profit_rr,
        max_open_trades=max_open_trades,
        cooldown_seconds=cooldown_seconds,
        demo_open_only=demo_open_only,
        demo_fill_mode=demo_fill_mode,
        fully_adaptive_engine=fully_adaptive_engine,
        binance_demo_api_key=binance_demo_api_key,
        binance_demo_api_secret=binance_demo_api_secret,
        binance_demo_base_url=binance_demo_base_url,
        relaxed_entry_for_testing=relaxed_entry_for_testing,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        jwt_expire_minutes=jwt_expire_minutes,
    )
