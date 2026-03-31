"""Validate ML inference prerequisites (features + one forward pass)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION
from src.ml.features import select_features


def feature_columns_valid(df: pd.DataFrame) -> bool:
    missing = [c for c in FEATURE_COLUMNS_PRODUCTION if c not in df.columns]
    return len(missing) == 0


def inference_smoke_test(ml_infer: Any, df: pd.DataFrame) -> Dict[str, Any]:
    """Returns inference_working + error string."""
    out: Dict[str, Any] = {"inference_working": False, "error": None}
    try:
        if not feature_columns_valid(df):
            out["error"] = "missing_feature_columns"
            return out
        _ = ml_infer.predict_window(df)
        out["inference_working"] = True
    except Exception as e:
        out["error"] = str(e)[:500]
    return out


def validate_features_or_raise(
    df: pd.DataFrame, columns: Optional[List[str]] = None
) -> None:
    """Strict path: no silent fallback."""
    from src.ml.feature_columns import FEATURE_COLUMNS_PRODUCTION

    select_features(df, columns or FEATURE_COLUMNS_PRODUCTION)
