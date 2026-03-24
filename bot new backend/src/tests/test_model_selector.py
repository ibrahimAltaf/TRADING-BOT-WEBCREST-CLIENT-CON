from pathlib import Path

from src.ml.model_selector import resolve_model_selection


def _touch_model_files(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.keras").write_text("x")


def test_selects_symbol_timeframe_specific_model(tmp_path: Path):
    base = tmp_path / "models" / "lstm_v1"
    specific = base / "BTCUSDT_1h"
    _touch_model_files(specific)

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="BTCUSDT",
        timeframe="1h",
        version=None,
    )

    assert resolved["model_exists"] is True
    assert resolved["specific_match"] is True
    assert resolved["model_name"] == "BTCUSDT_1h"


def test_falls_back_to_version_base_model(tmp_path: Path):
    base = tmp_path / "models" / "lstm_v1"
    _touch_model_files(base)

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="ETHUSDT",
        timeframe="15m",
        version=None,
    )

    assert resolved["model_exists"] is True
    assert resolved["specific_match"] is False
    assert resolved["model_name"] == "lstm_v1"


def test_version_override_prefers_repo_models_folder(tmp_path: Path, monkeypatch):
    base = tmp_path / "models" / "lstm_v1"
    _touch_model_files(base)

    repo_root = tmp_path / "repo"
    module_file = repo_root / "src" / "ml" / "model_selector.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# test module path")

    version_specific = repo_root / "models" / "lstm_v2" / "ETHUSDT_1h"
    _touch_model_files(version_specific)

    # Force model_selector._repo_root() to point to our temp repo root.
    monkeypatch.setattr(
        "src.ml.model_selector._repo_root",
        lambda: repo_root,
    )

    resolved = resolve_model_selection(
        base_model_dir=str(base),
        symbol="ETHUSDT",
        timeframe="1h",
        version="lstm_v2",
    )

    assert resolved["model_version"] == "lstm_v2"
    assert resolved["model_name"] == "ETHUSDT_1h"
    assert resolved["specific_match"] is True
    assert resolved["model_exists"] is True
