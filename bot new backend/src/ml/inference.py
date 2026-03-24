from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from src.ml.features import select_features, FEATURE_COLUMNS

_CLASSES = ["SELL", "HOLD", "BUY"]


def _import_tensorflow():
    """Lazy import so app starts without TensorFlow when ML_ENABLED=false."""
    try:
        import tensorflow as tf

        return tf
    except ImportError as e:
        raise ImportError(
            "TensorFlow is required for ML inference. Install with: pip install -r requirements-ml.txt "
            "(Use Python 3.11 or 3.12; TensorFlow does not support 3.14 yet)."
        ) from e


class LstmInfer:
    def __init__(self, model_dir: str):
        tf = _import_tensorflow()
        self.model_dir = Path(model_dir)
        self.model = tf.keras.models.load_model(self.model_dir / "model.keras")

        scaler = json.loads((self.model_dir / "scaler.json").read_text())
        self.mean = np.asarray(scaler["mean"], dtype=np.float32)
        self.scale = np.asarray(scaler["scale"], dtype=np.float32)

        meta = json.loads((self.model_dir / "meta.json").read_text())
        self.lookback = int(meta["lookback"])

    def _scale(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.scale

    def predict_window(self, window_df: pd.DataFrame) -> dict:
        feats = select_features(window_df)
        if len(feats) < self.lookback:
            raise ValueError(f"Need {self.lookback} rows, got {len(feats)}")

        last = feats.tail(self.lookback).to_numpy(dtype=np.float32)
        last = self._scale(last)
        X = last.reshape(1, self.lookback, len(FEATURE_COLUMNS))

        probs = self.model.predict(X, verbose=0)[0]  # (3,)
        idx = int(np.argmax(probs))
        return {
            "down": float(probs[0]),
            "hold": float(probs[1]),
            "up": float(probs[2]),
            "signal": _CLASSES[idx],
            "confidence": float(probs[idx]),
        }


_cache: dict[str, LstmInfer] = {}


def get_infer(model_dir: str) -> LstmInfer:
    key = str(Path(model_dir).resolve())
    infer = _cache.get(key)
    if infer is None:
        infer = LstmInfer(key)
        _cache[key] = infer
    return infer
