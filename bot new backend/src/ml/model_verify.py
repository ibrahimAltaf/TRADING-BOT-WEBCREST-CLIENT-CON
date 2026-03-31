"""Verify model.keras / scaler.json / meta.json on disk (production gate)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def check_model_artifacts(model_dir: Path) -> Dict[str, Any]:
    """Return existence flags + ok if all three required files exist."""
    d = Path(model_dir).resolve()
    keras = d / "model.keras"
    scaler = d / "scaler.json"
    meta = d / "meta.json"
    return {
        "model_dir": str(d),
        "model_keras": keras.is_file(),
        "scaler_json": scaler.is_file(),
        "meta_json": meta.is_file(),
        "all_present": keras.is_file() and scaler.is_file() and meta.is_file(),
    }
