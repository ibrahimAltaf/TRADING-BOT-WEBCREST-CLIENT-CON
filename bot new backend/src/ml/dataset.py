from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.ml.features import select_features, FEATURE_COLUMNS


@dataclass
class DatasetConfig:
    lookback: int = 100
    thr: float = 0.005  # 0.5% — higher threshold produces cleaner BUY/SELL labels
    out_dir: str = "models/lstm_v1"


def make_labels(close: np.ndarray, thr: float) -> np.ndarray:
    """
    Generate SELL(0)/HOLD(1)/BUY(2) labels from next-bar return.
    Higher threshold (0.005 = 0.5%) produces cleaner signal, fewer HOLD=noise rows.
    """
    ret1 = (close[1:] - close[:-1]) / close[:-1]
    y = np.full(ret1.shape, 1, dtype=np.int64)  # HOLD=1
    y[ret1 > thr] = 2  # BUY=2
    y[ret1 < -thr] = 0  # SELL=0
    return y  # len = n-1


def build_sequences(
    X: np.ndarray, y: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray]:
    # X: (n, f), y: (n-1,)
    n = X.shape[0]
    xs, ys = [], []
    for t in range(lookback - 1, n - 1):
        xs.append(X[t - lookback + 1 : t + 1])
        ys.append(y[t])
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.int64)


def time_split(xs, ys, train=0.70, val=0.15):
    n = len(xs)
    n_train = int(n * train)
    n_val = int(n * val)
    X_train, y_train = xs[:n_train], ys[:n_train]
    X_val, y_val = xs[n_train : n_train + n_val], ys[n_train : n_train + n_val]
    X_test, y_test = xs[n_train + n_val :], ys[n_train + n_val :]
    return (X_train, y_train), (X_val, y_val), (X_test, y_test)


def prepare_from_parquet(features_path: str, cfg: DatasetConfig):
    df = pd.read_parquet(features_path).sort_values("open_time").reset_index(drop=True)

    feats = select_features(df)
    close = df["close"].to_numpy(dtype=np.float32)

    y = make_labels(close, cfg.thr)  # (n-1,)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(feats.to_numpy(dtype=np.float32))  # (n,f)

    xs, ys = build_sequences(X_scaled, y, cfg.lookback)

    (Xtr, ytr), (Xva, yva), (Xte, yte) = time_split(xs, ys)

    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        out_dir / "dataset.npz", Xtr=Xtr, ytr=ytr, Xva=Xva, yva=yva, Xte=Xte, yte=yte
    )

    scaler_payload = {
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "features": FEATURE_COLUMNS,
    }
    (out_dir / "scaler.json").write_text(json.dumps(scaler_payload, indent=2))

    meta = {
        "lookback": cfg.lookback,
        "thr": cfg.thr,
        "n_features": len(FEATURE_COLUMNS),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    return str(out_dir / "dataset.npz")
