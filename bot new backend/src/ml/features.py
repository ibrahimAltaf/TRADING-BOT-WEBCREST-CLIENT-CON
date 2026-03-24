import pandas as pd

FEATURE_COLUMNS = [
    "open","high","low","close","volume",
    "ema_20","ema_50","rsi_14","atr_14",
    "macd","macd_signal","macd_hist",
    "vol_sma_20","vol_ratio",
]

def select_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    return df[FEATURE_COLUMNS].copy()
