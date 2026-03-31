"""
Production decision envelope: one structured object per cycle (audit / ML / rules).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import math


class HoldKind(str, Enum):
    NONE = "NONE"
    MARKET = "HOLD_MARKET"
    RISK = "HOLD_RISK"
    ML_FAIL = "HOLD_ML_FAIL"
    ERROR = "HOLD_ERROR"
    GATE = "HOLD_GATE"
    EXECUTION = "HOLD_EXECUTION"


def fuse_confidence(
    rule_action: str,
    ml_action: Optional[str],
    rule_conf: float,
    ml_conf: Optional[float],
) -> float:
    """Dynamic final confidence — not a flat 0.5."""
    rc = max(0.0, min(1.0, float(rule_conf)))
    if ml_conf is None or ml_action is None:
        return round(rc, 4)
    mc = max(0.0, min(1.0, float(ml_conf)))
    agree = rule_action == ml_action
    if agree:
        out = min(1.0, 0.6 * rc + 0.4 * mc + 0.1)
    else:
        # Disagreement: weight ML higher when softmax is moderate+ (≥0.6)
        if mc >= 0.6:
            out = 0.35 * rc + 0.65 * mc
        else:
            out = 0.5 * rc + 0.5 * mc
    return round(max(0.0, min(1.0, out)), 4)


def evaluate_entry_gates(
    *,
    adx: float,
    rsi: float,
    atr_pct: float,
    ema_fast: float,
    ema_slow: float,
    adx_threshold: float,
    atr_vol_threshold: float,
    rsi_buy_min: float,
    rsi_buy_max: float,
    ml_ok: bool = True,
    risk_ok: bool = True,
) -> Dict[str, Any]:
    """Transparent gate booleans + which failed (for HOLD diagnostics)."""
    # Relaxed vs strict trend: more cycles pass gates so ML-driven trades are not blocked
    trend_ok = bool(adx >= adx_threshold * 0.65) or (ema_fast != ema_slow)
    momentum_ok = (
        (rsi_buy_min - 5) <= rsi <= (rsi_buy_max + 5)
        or rsi < 35
        or rsi > 65
    )
    volatility_ok = atr_vol_threshold * 0.12 <= atr_pct <= atr_vol_threshold * 4.5
    gates = {
        "trend_ok": trend_ok,
        "momentum_ok": momentum_ok,
        "volatility_ok": volatility_ok,
        "ml_ok": ml_ok,
        "risk_ok": risk_ok,
    }
    failed = [k for k, v in gates.items() if not v]
    return {"gates": gates, "failed_gates": failed}


def classify_hold(
    *,
    final_action: str,
    gate_failed: List[str],
    ml_error: Optional[str],
    model_loaded: bool,
    ml_enabled: bool,
    execution_blocked_reason: Optional[str],
    cooldown: bool,
) -> Tuple[HoldKind, List[str]]:
    """HOLD must never be silent — always typed + reasons."""
    if final_action != "HOLD":
        return HoldKind.NONE, []

    if cooldown:
        return HoldKind.RISK, ["cooldown_active"]
    if ml_enabled and not model_loaded:
        return HoldKind.ML_FAIL, ["model_not_loaded_or_missing"]
    if ml_error:
        return HoldKind.ML_FAIL, [f"ml_error:{ml_error[:200]}"]
    if execution_blocked_reason:
        return HoldKind.EXECUTION, [execution_blocked_reason]
    if gate_failed:
        return HoldKind.GATE, [f"gate:{g}" for g in gate_failed]
    return HoldKind.MARKET, ["no_rule_or_ml_trade_signal_this_bar"]


@dataclass
class CycleEnvelope:
    symbol: str
    timeframe: str
    rule_signal: str
    rule_confidence: float
    ml_signal: Optional[str]
    ml_confidence: Optional[float]
    model_loaded: bool
    feature_columns_present: bool
    combined_signal: str
    combined_confidence: float
    final_signal: str
    final_confidence: float
    final_source: str
    execution_eligible: bool
    block_reason: List[str]
    hold_kind: str
    gates: Dict[str, bool] = field(default_factory=dict)
    ml_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "rule_signal": self.rule_signal,
            "rule_confidence": self.rule_confidence,
            "ml_signal": self.ml_signal,
            "ml_confidence": self.ml_confidence,
            "model_loaded": self.model_loaded,
            "feature_columns_present": self.feature_columns_present,
            "combined_signal": self.combined_signal,
            "combined_confidence": self.combined_confidence,
            "final_signal": self.final_signal,
            "final_confidence": self.final_confidence,
            "final_source": self.final_source,
            "execution_eligible": self.execution_eligible,
            "block_reason": self.block_reason,
            "hold_kind": self.hold_kind,
            "gates": self.gates,
            "ml_error": self.ml_error,
        }


def build_envelope_from_engine_state(
    *,
    symbol: str,
    timeframe: str,
    rule_signal: str,
    rule_confidence: float,
    ml_signal: Optional[str],
    ml_confidence: Optional[float],
    model_loaded: bool,
    feature_columns_present: bool,
    final_action: str,
    final_confidence: float,
    final_source: str,
    execution_eligible: bool,
    gate_eval: Dict[str, Any],
    ml_error: Optional[str],
    ml_enabled: bool,
    cooldown_blocked: bool,
    execution_block_reason: Optional[str] = None,
) -> CycleEnvelope:
    """Assemble envelope after rule+ML fusion (single place for audit)."""
    combined_signal = final_action
    combined_conf = fuse_confidence(
        rule_signal,
        ml_signal,
        rule_confidence,
        ml_confidence,
    )
    fc = final_confidence
    if math.isfinite(fc):
        fc = float(fc)
    else:
        fc = combined_conf

    failed_gates = list(gate_eval.get("failed_gates") or [])
    hold_kind, hold_reasons = classify_hold(
        final_action=final_action,
        gate_failed=failed_gates,
        ml_error=ml_error,
        model_loaded=model_loaded,
        ml_enabled=ml_enabled,
        execution_blocked_reason=execution_block_reason,
        cooldown=cooldown_blocked,
    )
    block = list(hold_reasons)
    if final_action == "HOLD" and hold_kind == HoldKind.MARKET:
        block = hold_reasons + ["see_override_reason_and_strategy_reason"]

    return CycleEnvelope(
        symbol=symbol,
        timeframe=timeframe,
        rule_signal=rule_signal,
        rule_confidence=round(rule_confidence, 4),
        ml_signal=ml_signal,
        ml_confidence=round(ml_confidence, 4) if ml_confidence is not None else None,
        model_loaded=model_loaded,
        feature_columns_present=feature_columns_present,
        combined_signal=combined_signal,
        combined_confidence=combined_conf,
        final_signal=final_action,
        final_confidence=round(fc, 4),
        final_source=final_source,
        execution_eligible=execution_eligible,
        block_reason=block,
        hold_kind=hold_kind.value,
        gates=gate_eval.get("gates") or {},
        ml_error=ml_error,
    )
