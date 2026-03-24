from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def _repo_root() -> Path:
    # src/ml/model_selector.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def resolve_model_selection(
    base_model_dir: str,
    symbol: str,
    timeframe: str,
    version: Optional[str] = None,
) -> Dict[str, object]:
    """Resolve the model directory using symbol/timeframe/version.

    Priority:
    1) models/<version>/<SYMBOL>_<timeframe>
    2) models/<version>
    3) <base_model_dir>/<SYMBOL>_<timeframe>
    4) <base_model_dir>
    """
    base_dir = Path(base_model_dir).resolve()
    norm_symbol = symbol.upper().strip()
    norm_tf = timeframe.strip()
    model_key = f"{norm_symbol}_{norm_tf}"

    version_dir = base_dir
    model_version = version.strip() if version else ""

    if model_version:
        project_version_dir = _repo_root() / "models" / model_version
        sibling_version_dir = base_dir.parent / model_version
        if project_version_dir.exists():
            version_dir = project_version_dir
        elif sibling_version_dir.exists():
            version_dir = sibling_version_dir
        else:
            version_dir = project_version_dir
    else:
        model_version = base_dir.name

    candidates = [
        version_dir / model_key,
        version_dir,
        base_dir / model_key,
        base_dir,
    ]

    selected = candidates[-1]
    for c in candidates:
        if (c / "model.keras").exists():
            selected = c
            break

    return {
        "symbol": norm_symbol,
        "timeframe": norm_tf,
        "model_version": model_version,
        "model_name": selected.name,
        "model_dir": str(selected),
        "model_key": model_key,
        "model_exists": (selected / "model.keras").exists(),
        "specific_match": selected.name == model_key,
    }
