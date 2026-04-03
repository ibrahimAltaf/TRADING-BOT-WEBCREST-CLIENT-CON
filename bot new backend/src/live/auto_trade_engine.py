from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import os

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.json_safe import finite_float, sanitize_for_json
from src.db.models import EventLog, Order, Position, TradingDecisionLog
from src.exchange.binance_spot_client import BinanceSpotClient
from src.risk.rules import CooldownState, RiskConfig
from src.features.indicators import add_all_indicators
from src.ml.dataset import append_ml_production_features
from src.live.adaptive_strategy import (
    AdaptiveStrategy,
    MarketRegime,
    TradingDecision,
    SignalAction,
)
from src.live.fully_adaptive_strategy import FullyAdaptiveStrategy
from src.ml.model_selector import resolve_model_selection
from src.live.cycle_decision import (
    RuntimeMode,
    build_envelope_from_engine_state,
    evaluate_entry_gates,
    fuse_confidence,
    resolve_runtime_mode,
)
from src.live.gate_stats import record_hold_kind
from src.ml.runtime_check import feature_columns_valid


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: SignalType
    confidence: float
    price: float
    timestamp: datetime
    source: str  # "rule_based" | "ml" | "combined" | "forced"
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class TradeResult:
    success: bool
    executed: bool
    signal: str
    reason: str

    order_id: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None
    position_id: Optional[int] = None

    exchange_status: Optional[str] = None
    executed_qty: Optional[float] = None
    cummulative_quote_qty: Optional[float] = None
    raw_order: Optional[Dict[str, Any]] = None


class AutoTradeEngine:
    """
    Live auto-trading engine:
    - Signal generation (rule-based + optional ML)
    - Position management
    - Risk checks
    - Market order execution (for deterministic Phase-1 demo)
    - Binance order status verification (GET /api/v3/order)
    - Database logging (EventLog + Order + Position)
    """

    def __init__(
        self,
        db: Session,
        client: Optional[BinanceSpotClient] = None,
        risk_config: Optional[RiskConfig] = None,
    ):
        self.db = db
        self.client = client or BinanceSpotClient()
        self.risk_config = risk_config or RiskConfig()
        self.settings = get_settings()
        self.cooldown = CooldownState()

        if getattr(self.settings, "fully_adaptive_engine", False):
            # Fully Adaptive Engine (dynamic params per bar)
            self.adaptive_strategy = FullyAdaptiveStrategy(self.settings)
        else:
            # Baseline adaptive strategy (static params from .env)
            strategy_config = {
                "adx_threshold": self.settings.adx_threshold,
                "atr_vol_threshold": self.settings.atr_vol_threshold,
                "ema_fast": self.settings.ema_fast,
                "ema_slow": self.settings.ema_slow,
                "rsi_len": self.settings.rsi_len,
                "rsi_buy_min": self.settings.rsi_buy_min,
                "rsi_buy_max": self.settings.rsi_buy_max,
                "rsi_take_profit": self.settings.rsi_take_profit,
                "bb_len": self.settings.bb_len,
                "bb_std": self.settings.bb_std,
                "rsi_range_buy": self.settings.rsi_range_buy,
                "rsi_range_sell": self.settings.rsi_range_sell,
                "max_risk_per_trade": self.settings.max_risk_per_trade,
                "stop_loss_atr_mult": self.settings.stop_loss_atr_mult,
                "take_profit_rr": self.settings.take_profit_rr,
                "relaxed_entry_for_testing": getattr(
                    self.settings, "relaxed_entry_for_testing", False
                ),
            }
            self.adaptive_strategy = AdaptiveStrategy(strategy_config)

        # ML inference (optional)
        self.ml_infer = None
        self.ml_enabled = bool(getattr(self.settings, "ml_enabled", False))
        self.ml_model_version = os.getenv("ML_MODEL_VERSION", "").strip() or None

    def _resolve_ml_context(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        return resolve_model_selection(
            base_model_dir=self.settings.ml_model_dir,
            symbol=symbol,
            timeframe=timeframe,
            version=self.ml_model_version,
        )

    # ---------------------------
    # Logging / DB helpers
    # ---------------------------

    def _dump_signals_json(self, signals: Any) -> str:
        try:
            payload = sanitize_for_json(signals if isinstance(signals, dict) else {})
            return json.dumps(payload, allow_nan=False)
        except Exception as e:
            return json.dumps(
                {"error": "signals_serialization_failed", "detail": str(e)[:500]},
                allow_nan=False,
            )

    def _log_event(
        self,
        level: str,
        category: str,
        message: str,
        symbol: Optional[str] = None,
    ) -> None:
        log = EventLog(
            level=level,
            category=category,
            message=message,
            symbol=symbol,
            ts=datetime.utcnow(),
        )
        self.db.add(log)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _resolve_local_order_id(
        self, exchange_order_id: Optional[Any]
    ) -> Optional[int]:
        """
        Convert Binance exchange orderId -> local DB Order.id (FK target).
        """
        if exchange_order_id is None:
            return None

        exchange_id = str(exchange_order_id).strip()
        if not exchange_id:
            return None

        row = (
            self.db.query(Order.id)
            .filter(Order.exchange_order_id == exchange_id)
            .order_by(Order.created_at.desc())
            .first()
        )
        if not row:
            return None

        return int(row[0])

    def _save_decision(
        self,
        decision: TradingDecision,
        symbol: str,
        timeframe: str,
        executed: bool = False,
        order_id: Optional[Any] = None,
    ) -> TradingDecisionLog:
        """
        Save trading decision to database for transparency/explainability.
        This is critical for dashboard display showing WHY decisions were made.
        """
        local_order_id = self._resolve_local_order_id(order_id)

        decision_log = TradingDecisionLog(
            action=decision.action.value,
            confidence=finite_float(decision.confidence, 0.0),
            symbol=symbol,
            timeframe=timeframe,
            regime=decision.regime.value,
            price=finite_float(decision.price, 0.0),
            ts=datetime.utcnow(),
            adx=finite_float(decision.adx, 0.0),
            ema_fast=finite_float(decision.ema_fast, 0.0),
            ema_slow=finite_float(decision.ema_slow, 0.0),
            rsi=finite_float(decision.rsi, 0.0),
            bb_upper=(
                finite_float(decision.bb_upper, 0.0)
                if decision.bb_upper is not None
                else None
            ),
            bb_lower=(
                finite_float(decision.bb_lower, 0.0)
                if decision.bb_lower is not None
                else None
            ),
            atr=finite_float(decision.atr, 0.0),
            entry_price=(
                finite_float(decision.entry_price, 0.0)
                if decision.entry_price is not None
                else None
            ),
            stop_loss=(
                finite_float(decision.stop_loss, 0.0)
                if decision.stop_loss is not None
                else None
            ),
            take_profit=(
                finite_float(decision.take_profit, 0.0)
                if decision.take_profit is not None
                else None
            ),
            risk_reward=(
                finite_float(decision.risk_reward, 0.0)
                if decision.risk_reward is not None
                else None
            ),
            reason=(decision.reason or "")[:20000],
            signals_json=_dump_signals_json(decision.signals),
            executed=executed,
            order_id=local_order_id,
        )
        self.db.add(decision_log)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(decision_log)
        return decision_log

    def _persist_engine_exception_audit(
        self,
        *,
        symbol: str,
        timeframe: str,
        exc: BaseException,
    ) -> None:
        """Persist a HOLD decision when the engine raises so audits never miss a cycle."""
        err_msg = str(exc)[:8000]
        sig: Dict[str, Any] = {
            "final_source": "engine_exception",
            "rule_signal": None,
            "ml_signal": None,
            "ml_confidence": None,
            "combined_signal": "HOLD",
            "override_reason": f"Unexpected engine exception: {type(exc).__name__}",
            "runtime_mode": RuntimeMode.AI_DEGRADED.value,
            "cycle_debug": {
                "symbol": symbol,
                "timeframe": timeframe,
                "runtime_mode": RuntimeMode.AI_DEGRADED.value,
                "rule_signal": None,
                "rule_confidence": None,
                "ml_signal": None,
                "ml_confidence": None,
                "combined_signal": "HOLD",
                "final_signal": "HOLD",
                "final_source": "engine_exception",
                "execution_eligible": False,
                "hold_kind": "runtime_hold",
                "block_reasons": [
                    f"exception_type:{type(exc).__name__}",
                    err_msg[:2000],
                ],
            },
            "engine_exception": {
                "type": type(exc).__name__,
                "message": err_msg,
            },
        }
        decision = TradingDecision(
            action=SignalAction.HOLD,
            confidence=0.0,
            regime=MarketRegime.UNKNOWN,
            price=0.0,
            timestamp=datetime.utcnow().isoformat(),
            adx=0.0,
            ema_fast=0.0,
            ema_slow=0.0,
            rsi=0.0,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            atr=0.0,
            atr_pct=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size_pct=0.0,
            reason=f"Engine exception ({type(exc).__name__}): {err_msg[:19000]}",
            signals=sig,
        )
        self._save_decision(
            decision, symbol=symbol, timeframe=timeframe, executed=False
        )

    def _enrich_cycle_debug(
        self,
        decision: TradingDecision,
        *,
        symbol: str,
        timeframe: str,
        runtime_mode: str,
        rule_signal_value: str,
        ml_signal_value: Optional[str],
        rule_confidence_before_ml: float,
        has_open_position: bool,
    ) -> None:
        """Structured audit: cycle_debug (envelope fills hold_kind / block_reasons)."""
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        ml_pred = sig.get("ml_prediction") or {}
        ml_conf = ml_pred.get("confidence")
        if ml_conf is not None:
            try:
                ml_conf = float(ml_conf)
            except Exception:
                ml_conf = None
        final_src = str(sig.get("final_source", "rule_only"))
        action = decision.action.value

        block_reasons: List[str] = []
        if action == "HOLD":
            ov = sig.get("override_reason")
            if ov:
                block_reasons.append(str(ov))
            block_reasons.append(str(decision.reason or "")[:800])
            if sig.get("ml_load_error"):
                block_reasons.append(f"ml_load_error: {sig['ml_load_error']}")
        elif action == "BUY" and has_open_position:
            block_reasons.append("BUY signal ignored: open position exists for symbol")
        elif action == "SELL" and not has_open_position:
            block_reasons.append("SELL signal ignored: no open position")

        execution_eligible = (action == "BUY" and not has_open_position) or (
            action == "SELL" and has_open_position
        )

        combined = sig.get("combined_signal") or action
        sig["cycle_debug"] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "runtime_mode": runtime_mode,
            "rule_signal": rule_signal_value,
            "rule_confidence": round(finite_float(rule_confidence_before_ml, 0.0), 4),
            "ml_signal": ml_signal_value,
            "ml_confidence": round(finite_float(ml_conf, 0.0), 4)
            if ml_conf is not None
            else None,
            "combined_signal": combined,
            "final_signal": action,
            "final_source": final_src,
            "hold_kind": None,
            "block_reasons": block_reasons,
            "execution_eligible": execution_eligible,
            "final_confidence": round(finite_float(decision.confidence, 0.0), 4),
            "has_open_position": has_open_position,
        }
        decision.signals = sig

    def _patch_cycle_execution_block(self, decision: TradingDecision, reason: str) -> None:
        if not isinstance(decision.signals, dict):
            return
        cd = decision.signals.get("cycle_debug") or {}
        cd["hold_kind"] = "blocked_execution_hold"
        cd["execution_block_reason"] = reason
        decision.signals["cycle_debug"] = cd

    def _attach_cycle_envelope(
        self,
        decision: TradingDecision,
        *,
        symbol: str,
        timeframe: str,
        runtime_mode: str,
        runtime_eligible: bool,
        rule_signal_value: str,
        rule_confidence_before_ml: float,
        ml_signal_str: Optional[str],
        ml_conf: Optional[float],
        model_loaded: bool,
        feature_columns_present: bool,
        final_source: str,
        open_position: Optional[Position],
        gate_eval: Dict[str, Any],
        ml_error: Optional[str],
        cooldown_blocked: bool,
    ) -> None:
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        cd = sig.get("cycle_debug") or {}
        exec_eligible = bool(cd.get("execution_eligible")) if cd else False
        env = build_envelope_from_engine_state(
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=runtime_mode,
            rule_signal=rule_signal_value,
            rule_confidence=rule_confidence_before_ml,
            ml_signal=ml_signal_str,
            ml_confidence=ml_conf,
            model_loaded=model_loaded,
            feature_columns_present=feature_columns_present,
            final_action=decision.action.value,
            final_confidence=float(decision.confidence),
            final_source=final_source,
            execution_eligible=exec_eligible,
            gate_eval=gate_eval,
            ml_error=ml_error
            or sig.get("ml_load_error")
            or sig.get("ml_prediction_error"),
            ml_enabled=self.ml_enabled,
            runtime_eligible=runtime_eligible,
            cooldown_blocked=cooldown_blocked,
            execution_block_reason=cd.get("execution_block_reason"),
        )
        sig["cycle_envelope"] = env.to_dict()
        cd["hold_kind"] = env.hold_kind
        cd["block_reasons"] = env.block_reason
        cd["runtime_mode"] = env.runtime_mode
        sig["cycle_debug"] = cd
        decision.signals = sig
        if env.final_signal == "HOLD" and env.hold_kind and env.hold_kind != "none":
            record_hold_kind(env.hold_kind)

    def _ml_strict_abort_trading_cycle(
        self,
        *,
        decision: TradingDecision,
        symbol: str,
        timeframe: str,
        rule_signal_value: str,
        rule_confidence_before_ml: float,
        current_price: float,
        df: Any,
        err: str,
        model_loaded: bool,
        ml_context: Dict[str, Any],
    ) -> TradeResult:
        """ML_STRICT: no silent rule-only path when ML pipeline is required."""
        decision.action = SignalAction.HOLD
        if not ml_context.get("runtime_eligible"):
            decision.reason = "AI runtime degraded"
        else:
            decision.reason = f"AI runtime degraded: {err}"
        decision.signals["final_source"] = "ml_strict_failure"
        decision.signals["combined_signal"] = "HOLD"
        decision.signals["rule_signal"] = rule_signal_value
        self._apply_ml_audit_fields(
            decision,
            ml_context=ml_context,
            ml_out=None,
            ml_infer_present=model_loaded,
            rule_signal_value=rule_signal_value,
        )
        open_position = self._get_open_position(symbol)
        gate_eval = evaluate_entry_gates(
            adx=float(decision.adx),
            rsi=float(decision.rsi),
            atr_pct=float(decision.atr_pct),
            ema_fast=float(decision.ema_fast),
            ema_slow=float(decision.ema_slow),
            adx_threshold=float(self.settings.adx_threshold),
            atr_vol_threshold=float(self.settings.atr_vol_threshold),
            rsi_buy_min=float(self.settings.rsi_buy_min),
            rsi_buy_max=float(self.settings.rsi_buy_max),
            ml_ok=False,
            risk_ok=True,
        )
        rt_mode = resolve_runtime_mode(
            ml_enabled=self.ml_enabled,
            runtime_eligible=bool(ml_context.get("runtime_eligible")),
            model_loaded=model_loaded,
            ml_signal_present=False,
            ml_error=err,
        ).value
        self._enrich_cycle_debug(
            decision,
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=rt_mode,
            rule_signal_value=rule_signal_value,
            ml_signal_value=None,
            rule_confidence_before_ml=rule_confidence_before_ml,
            has_open_position=open_position is not None,
        )
        self._attach_cycle_envelope(
            decision,
            symbol=symbol,
            timeframe=timeframe,
            runtime_mode=rt_mode,
            runtime_eligible=bool(ml_context.get("runtime_eligible")),
            rule_signal_value=rule_signal_value,
            rule_confidence_before_ml=rule_confidence_before_ml,
            ml_signal_str=decision.signals.get("ml_signal"),
            ml_conf=decision.signals.get("ml_confidence"),
            model_loaded=model_loaded,
            feature_columns_present=feature_columns_valid(df),
            final_source="ml_strict_failure",
            open_position=open_position,
            gate_eval=gate_eval,
            ml_error=err,
            cooldown_blocked=False,
        )
        self._save_decision(decision, symbol, timeframe, executed=False)
        self._log_event(
            "ERROR",
            "ml",
            f"ML_STRICT abort: {err} (symbol={symbol} tf={timeframe})",
            symbol=symbol,
        )
        return TradeResult(
            success=False,
            executed=False,
            signal="HOLD",
            reason=decision.reason,
            price=current_price,
        )

    def _apply_ml_audit_fields(
        self,
        decision: TradingDecision,
        *,
        ml_context: Dict[str, Any],
        ml_out: Optional[TradeSignal],
        ml_infer_present: bool,
        rule_signal_value: str,
    ) -> None:
        """Always persist ml_signal, ml_confidence, ml_status, final_source for diagnostics."""
        sig = decision.signals if isinstance(decision.signals, dict) else {}
        ml_strict = bool(getattr(self.settings, "ml_strict", False))
        if not self.ml_enabled:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "ml_disabled"
            sig["final_source"] = sig.get("final_source", "rule_only_ml_disabled")
            decision.signals = sig
            return

        if not ml_context.get("runtime_eligible"):
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "runtime_not_eligible"
            if not ml_strict:
                self._log_event(
                    "WARN",
                    "ml",
                    "ML_ENABLED but no exact model package for symbol/timeframe — rules-only path",
                    symbol=ml_context.get("symbol"),
                )
        elif not ml_infer_present:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "model_load_failed"
        elif ml_out is None:
            sig["ml_signal"] = None
            sig["ml_confidence"] = None
            sig["ml_status"] = "inference_failed"
        else:
            sig["ml_signal"] = ml_out.signal.value
            sig["ml_confidence"] = round(float(ml_out.confidence), 4)
            sig["ml_status"] = "ok"
            pred = sig.get("ml_prediction") or {}
            if not pred:
                ml_meta = ml_out.metadata or {}
                sig["ml_prediction"] = {
                    "signal": ml_out.signal.value,
                    "confidence": round(ml_out.confidence, 3),
                    "up": round(float(ml_meta.get("up", 0)), 3),
                    "hold": round(float(ml_meta.get("hold", 0)), 3),
                    "down": round(float(ml_meta.get("down", 0)), 3),
                }

        fs = str(sig.get("final_source", "rule_only"))
        if (
            self.ml_enabled
            and ml_out is not None
            and sig.get("ml_status") == "ok"
            and fs == "rule_only"
            and not ml_strict
        ):
            self._log_event(
                "WARN",
                "ml",
                f"ML did not change final decision (rules retained): rule={rule_signal_value} "
                f"vs ml={ml_out.signal.value} @ {ml_out.confidence:.2f}",
                symbol=ml_context.get("symbol"),
            )
        decision.signals = sig

    def _get_open_position(self, symbol: str) -> Optional[Position]:
        return (
            self.db.query(Position)
            .filter(
                Position.symbol == symbol,
                Position.is_open == True,  # noqa: E712
                Position.mode == "live",
            )
            .first()
        )

    def _get_usdt_balance(self) -> float:
        account = self.client.account()
        usdt = next(
            (b for b in account.get("balances", []) if b.get("asset") == "USDT"),
            {"free": "0"},
        )
        return float(usdt.get("free", "0") or 0)

    def _create_position(
        self, symbol: str, entry_price: float, quantity: float
    ) -> Position:
        position = Position(
            mode="live",
            symbol=symbol,
            is_open=True,
            entry_price=entry_price,
            entry_qty=quantity,
            entry_ts=datetime.utcnow(),
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)
        return position

    def _close_position(
        self, position: Position, exit_price: float, exit_qty: float
    ) -> None:
        position.is_open = False
        position.exit_price = exit_price
        position.exit_qty = exit_qty
        position.exit_ts = datetime.utcnow()

        # P&L
        position.pnl = (exit_price - position.entry_price) * exit_qty
        position.pnl_pct = (
            (exit_price - position.entry_price) / position.entry_price
        ) * 100

        self.db.commit()

    def _record_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        requested_price: float,
        order_response: Dict[str, Any],
        order_type: str,
        status: str,
        executed_price: Optional[float] = None,
    ) -> Order:
        """
        Records an order in DB with REAL orderType + REAL status.
        Note: if your Order model doesn't have some fields, remove them accordingly.
        """
        o = Order(
            mode="live",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            requested_price=requested_price,
            executed_price=executed_price,
            status=status,
            exchange_order_id=str(order_response.get("orderId", "")),
            created_at=datetime.utcnow(),
        )
        self.db.add(o)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(o)
        return o

    # ---------------------------
    # Signals
    # ---------------------------

    def _generate_rule_based_signal(self, df) -> TradeSignal:
        from src.backtest.engine import generate_signal

        last_row = df.iloc[-1]
        signal_str = generate_signal(last_row)

        if signal_str == "BUY":
            sig = SignalType.BUY
        elif signal_str == "SELL":
            sig = SignalType.SELL
        else:
            sig = SignalType.HOLD

        return TradeSignal(
            signal=sig,
            confidence=0.7,
            price=float(last_row["close"]),
            timestamp=datetime.utcnow(),
            source="rule_based",
        )

    def _generate_ml_signal(self, df) -> Optional[TradeSignal]:
        if not self.ml_infer:
            return None
        result = self.ml_infer.predict_window(df)

        # NOTE: inference.py returns _CLASSES = ["SELL","HOLD","BUY"]
        raw_signal = str(result.get("signal", "HOLD")).upper()
        if raw_signal == "BUY":
            sig = SignalType.BUY
        elif raw_signal == "SELL":
            sig = SignalType.SELL
        else:
            sig = SignalType.HOLD

        self._log_event(
            "INFO",
            "ml",
            f"ML prediction: signal={raw_signal} confidence={result.get('confidence', 0):.3f} "
            f"up={result.get('up', 0):.3f} hold={result.get('hold', 0):.3f} down={result.get('down', 0):.3f}",
        )

        return TradeSignal(
            signal=sig,
            confidence=float(result.get("confidence", 0.0)),
            price=float(df.iloc[-1]["close"]),
            timestamp=datetime.utcnow(),
            source="ml",
            metadata=result,
        )

    def _combine_signals(
        self,
        rule_signal: TradeSignal,
        ml_signal: Optional[TradeSignal],
        *,
        strict_ai: bool = False,
    ) -> TradeSignal:
        if not ml_signal:
            return rule_signal

        prioritize_th = float(
            getattr(self.settings, "ml_prioritize_threshold", 0.80)
        )
        override_th = float(getattr(self.settings, "ml_override_threshold", 0.70))
        agree_th = float(getattr(self.settings, "ml_agree_threshold", 0.70))

        if ml_signal.confidence >= prioritize_th:
            self._log_event(
                "INFO",
                "signal",
                f"ML prioritize (high conf): {ml_signal.signal.value} @ {ml_signal.confidence:.2f}",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=ml_signal.confidence,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_prioritize",
                metadata=ml_signal.metadata,
            )

        if ml_signal.confidence >= override_th:
            self._log_event(
                "INFO",
                "signal",
                f"ML override: {ml_signal.signal.value} @ {ml_signal.confidence:.2f}",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=ml_signal.confidence,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_override",
                metadata=ml_signal.metadata,
            )

        if rule_signal.signal == ml_signal.signal and ml_signal.confidence >= agree_th:
            combined_conf = (rule_signal.confidence + ml_signal.confidence) / 2
            self._log_event(
                "INFO",
                "signal",
                f"Signals agree: {rule_signal.signal.value} @ {combined_conf:.2f}",
            )
            return TradeSignal(
                signal=rule_signal.signal,
                confidence=combined_conf,
                price=rule_signal.price,
                timestamp=rule_signal.timestamp,
                source="combined",
                metadata={"rule": rule_signal.metadata, "ml": ml_signal.metadata},
            )

        abs_floor = float(
            getattr(self.settings, "ml_absolute_min_confidence", 0.50)
        )
        # Directional conflict (BUY vs SELL): let ML win below override threshold but above safety floor
        if (
            rule_signal.signal in (SignalType.BUY, SignalType.SELL)
            and ml_signal.signal in (SignalType.BUY, SignalType.SELL)
            and rule_signal.signal != ml_signal.signal
            and abs_floor <= float(ml_signal.confidence) < override_th
        ):
            blended = min(
                0.95,
                0.35 * float(rule_signal.confidence)
                + 0.65 * float(ml_signal.confidence),
            )
            self._log_event(
                "INFO",
                "signal",
                f"ML moderate influence: {ml_signal.signal.value} @ {ml_signal.confidence:.2f} "
                f"(rule={rule_signal.signal.value}, blended={blended:.2f})",
            )
            return TradeSignal(
                signal=ml_signal.signal,
                confidence=blended,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_moderate_influence",
                metadata=ml_signal.metadata,
            )

        # Stronger AI: rules say HOLD but ML has directional conviction (reduces HOLD-only stagnation)
        if getattr(self.settings, "ml_hold_breakout_enabled", True):
            hb_min = float(
                getattr(self.settings, "ml_hold_breakout_min_confidence", 0.58)
            )
            if (
                rule_signal.signal == SignalType.HOLD
                and ml_signal.signal in (SignalType.BUY, SignalType.SELL)
                and float(ml_signal.confidence) >= hb_min
            ):
                blended = min(
                    0.95,
                    0.4 * float(rule_signal.confidence)
                    + 0.6 * float(ml_signal.confidence),
                )
                self._log_event(
                    "INFO",
                    "signal",
                    f"ML hold-breakout: {ml_signal.signal.value} @ {ml_signal.confidence:.2f} "
                    f"(rule=HOLD, blended_conf={blended:.2f})",
                )
                return TradeSignal(
                    signal=ml_signal.signal,
                    confidence=blended,
                    price=ml_signal.price,
                    timestamp=ml_signal.timestamp,
                    source="ml_hold_breakout",
                    metadata=ml_signal.metadata,
                )

        if strict_ai:
            self._log_event(
                "INFO",
                "signal",
                f"Strict AI: rule/ML conflict → HOLD (rule={rule_signal.signal.value}, "
                f"ml={ml_signal.signal.value})",
            )
            blend = min(
                0.55,
                0.5 * float(rule_signal.confidence) + 0.5 * float(ml_signal.confidence),
            )
            return TradeSignal(
                signal=SignalType.HOLD,
                confidence=blend,
                price=ml_signal.price,
                timestamp=ml_signal.timestamp,
                source="ml_rule_conflict_hold",
                metadata={"rule": rule_signal.metadata, "ml": ml_signal.metadata},
            )

        self._log_event(
            "INFO",
            "signal",
            f"Signal conflict - using rule-based: {rule_signal.signal.value}",
        )
        return TradeSignal(
            signal=rule_signal.signal,
            confidence=rule_signal.confidence,
            price=rule_signal.price,
            timestamp=rule_signal.timestamp,
            source="rule_only",
            metadata={"ml_conflict": getattr(ml_signal, "metadata", None)},
        )

    # ---------------------------
    # Binance verification helpers
    # ---------------------------

    def _sync_order_status(self, symbol: str, exchange_order_id: int) -> Dict[str, Any]:
        """
        Query Binance for order status (Phase 1 proof)
        """
        info = self.client.get_order(symbol=symbol, order_id=exchange_order_id)
        self._log_event(
            "INFO",
            "order",
            f"Order status: orderId={exchange_order_id} status={info.get('status')} "
            f"executedQty={info.get('executedQty')} cumQuote={info.get('cummulativeQuoteQty')}",
            symbol=symbol,
        )
        return info

    # ---------------------------
    # Risk sizing
    # ---------------------------

    def _calculate_position_size(
        self, balance: float, price: float, risk_pct: Optional[float] = None
    ) -> tuple[float, float]:
        risk_pct = (
            risk_pct
            if risk_pct is not None
            else float(self.risk_config.max_position_pct)
        )
        spend = balance * float(risk_pct)
        quantity = spend / price if price > 0 else 0.0
        return quantity, spend

    def _position_size_from_risk(
        self,
        *,
        balance: float,
        price: float,
        stop_loss: Optional[float],
        risk_pct: Optional[float],
    ) -> tuple[bool, float, float, str]:
        """Returns (ok, quantity, spend, reason) using deterministic risk sizing when stop is set."""
        from src.risk.position_sizing import compute_position_size

        max_pos_pct = float(
            risk_pct
            if risk_pct is not None
            else self.risk_config.max_position_pct
        )
        rp = float(self.settings.max_risk_per_trade)
        if (
            stop_loss is not None
            and stop_loss > 0
            and price > 0
            and stop_loss < price
        ):
            out = compute_position_size(
                equity=balance,
                entry_price=price,
                stop_loss=float(stop_loss),
                max_position_pct=max_pos_pct,
                risk_per_trade_pct=rp,
            )
            if not out["ok"]:
                return False, 0.0, 0.0, str(out["reason"])
            qty = float(out["qty"])
            spend = qty * price
            return True, qty, spend, "risk_and_notional_cap"
        qty, spend = self._calculate_position_size(balance, price, risk_pct)
        return True, qty, spend, "notional_cap_only"

    # ---------------------------
    # Main entry
    # ---------------------------

    def execute_auto_trade(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        risk_pct: Optional[float] = None,
        force_signal: Optional[str] = None,  # "BUY" | "SELL"
    ) -> TradeResult:
        now = datetime.utcnow()
        symbol = symbol or self.settings.trade_symbol
        timeframe = timeframe or self.settings.trade_timeframe

        if self.cooldown.blocked(now):
            return TradeResult(
                success=True,
                executed=False,
                signal="HOLD",
                reason=f"Cooldown active until {self.cooldown.until}",
            )

        try:
            lookback = int(getattr(self.settings, "trade_lookback", 500))
            klines = self.client.klines(
                symbol=symbol, interval=timeframe, limit=lookback
            )

            # Convert klines to DataFrame
            import pandas as pd

            df = pd.DataFrame(
                klines,
                columns=[
                    "open_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "qav",
                    "num_trades",
                    "taker_base",
                    "taker_quote",
                    "ignore",
                ],
            )
            df.loc[:, "open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df.loc[:, col] = df[col].astype(float)

            indicator_config = {
                "ema_fast": self.settings.ema_fast,
                "ema_slow": self.settings.ema_slow,
                "rsi_period": self.settings.rsi_len,
                "adx_period": 14,
                "bb_period": self.settings.bb_len,
                "bb_std": self.settings.bb_std,
                "atr_period": 14,
            }
            df = add_all_indicators(df, indicator_config)
            df = append_ml_production_features(df)
            df = df.dropna()

            if len(df) < 50:
                return TradeResult(
                    success=False,
                    executed=False,
                    signal="HOLD",
                    reason="Insufficient data after indicator calculation",
                )

            if force_signal:
                # Manual override for testing
                fs = force_signal.upper().strip()
                if fs not in ("BUY", "SELL", "HOLD"):
                    raise ValueError(
                        f"force_signal must be BUY/SELL/HOLD, got {force_signal!r}"
                    )

                # Still save a decision log for transparency
                last_price = float(df.iloc[-1]["close"])
                decision_log = self._save_decision(
                    decision=TradingDecision(
                        action=SignalAction[fs],
                        confidence=1.0,
                        regime=(
                            "FORCED"
                            if hasattr(
                                self.adaptive_strategy.detect_regime(df).regime, "value"
                            )
                            else "UNKNOWN"
                        ),
                        price=last_price,
                        timestamp=pd.Timestamp.now().isoformat(),
                        adx=0,
                        ema_fast=0,
                        ema_slow=0,
                        rsi=0,
                        bb_upper=None,
                        bb_middle=None,
                        bb_lower=None,
                        atr=0,
                        atr_pct=0,
                        entry_price=last_price if fs != "HOLD" else None,
                        stop_loss=None,
                        take_profit=None,
                        risk_reward=None,
                        position_size_pct=0,
                        reason=f"Forced signal: {fs}",
                        signals={"forced": True},
                    ),
                    symbol=symbol,
                    timeframe=timeframe,
                )

                # Execute based on forced signal
                if fs == "BUY":
                    open_position = self._get_open_position(symbol)
                    if not open_position:
                        result = self._execute_buy(
                            symbol=symbol, price=last_price, risk_pct=risk_pct
                        )
                        if result.executed:
                            decision_log.executed = True
                            decision_log.order_id = self._resolve_local_order_id(
                                result.order_id
                            )
                            try:
                                self.db.commit()
                            except Exception:
                                self.db.rollback()
                                raise
                        return result
                elif fs == "SELL":
                    open_position = self._get_open_position(symbol)
                    if open_position:
                        result = self._execute_sell(
                            symbol=symbol, position=open_position, price=last_price
                        )
                        if result.executed:
                            decision_log.executed = True
                            decision_log.order_id = self._resolve_local_order_id(
                                result.order_id
                            )
                            try:
                                self.db.commit()
                            except Exception:
                                self.db.rollback()
                                raise
                        return result

                return TradeResult(
                    success=True,
                    executed=False,
                    signal=fs,
                    reason=f"Forced {fs} but conditions not met",
                )

            decision: TradingDecision = self.adaptive_strategy.generate_decision(df)

            rule_confidence_before_ml = float(decision.confidence)
            current_price = decision.price
            rule_signal_value: str = (
                decision.action.value
            )  # capture rule output for audit

            self._log_event(
                "INFO",
                "signal",
                f"[RULE] {symbol} {timeframe}: {decision.action.value} "
                f"conf={decision.confidence:.2f} regime={decision.regime.value} | {decision.reason}",
                symbol=symbol,
            )

            ml_signal_value: Optional[str] = None  # set if ML runs, for audit log
            ml_context: Dict[str, Any] = self._resolve_ml_context(symbol, timeframe)
            ml_changed_final_action = False
            ml_out: Optional[TradeSignal] = None
            runtime_eligible = bool(ml_context.get("runtime_eligible"))
            strict_ai = bool(
                self.ml_enabled
                and runtime_eligible
                and getattr(self.settings, "ml_strict", True)
            )

            self.ml_infer = None

            if self.ml_enabled and not runtime_eligible:
                decision.signals["ml_load_error"] = ml_context.get(
                    "reason", "runtime_not_eligible"
                )
                decision.signals["final_source"] = "ml_strict_failure"
                return self._ml_strict_abort_trading_cycle(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    rule_signal_value=rule_signal_value,
                    rule_confidence_before_ml=rule_confidence_before_ml,
                    current_price=current_price,
                    df=df,
                    err=str(ml_context.get("reason", "runtime_not_eligible")),
                    model_loaded=False,
                    ml_context=ml_context,
                )

            if self.ml_enabled and runtime_eligible:
                try:
                    from src.ml.inference import get_infer

                    self.ml_infer = get_infer(str(ml_context["model_dir"]))
                except Exception as e:
                    decision.signals["ml_load_error"] = str(e)
                    self.ml_infer = None

            if self.ml_enabled and runtime_eligible and not self.ml_infer:
                err = str(decision.signals.get("ml_load_error") or "model_load_failed")
                return self._ml_strict_abort_trading_cycle(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    rule_signal_value=rule_signal_value,
                    rule_confidence_before_ml=rule_confidence_before_ml,
                    current_price=current_price,
                    df=df,
                    err=err,
                    model_loaded=False,
                    ml_context=ml_context,
                )

            if self.ml_infer:
                try:
                    ml_out = self._generate_ml_signal(df)
                except Exception as e:
                    self._log_event("ERROR", "ml", f"ML prediction failed: {e}", symbol=symbol)
                    decision.signals["ml_prediction_error"] = str(e)
                    return self._ml_strict_abort_trading_cycle(
                        decision=decision,
                        symbol=symbol,
                        timeframe=timeframe,
                        rule_signal_value=rule_signal_value,
                        rule_confidence_before_ml=rule_confidence_before_ml,
                        current_price=current_price,
                        df=df,
                        err=str(e),
                        model_loaded=True,
                        ml_context=ml_context,
                    )
                if ml_out:
                    ml_signal_value = ml_out.signal.value
                    rule_signal = TradeSignal(
                        signal=SignalType[decision.action.value],
                        confidence=decision.confidence,
                        price=decision.price,
                        timestamp=datetime.utcnow(),
                        source="rule_based",
                    )
                    final_signal = self._combine_signals(
                        rule_signal, ml_out, strict_ai=strict_ai
                    )

                    fused = fuse_confidence(
                        rule_signal_value,
                        ml_out.signal.value,
                        rule_confidence_before_ml,
                        ml_out.confidence,
                    )
                    if final_signal.source in ("ml_override", "ml_prioritize"):
                        decision.confidence = final_signal.confidence
                    elif final_signal.source in (
                        "ml_hold_breakout",
                        "ml_moderate_influence",
                    ):
                        decision.confidence = min(
                            1.0, max(fused, final_signal.confidence)
                        )
                    elif final_signal.source == "ml_rule_conflict_hold":
                        decision.confidence = final_signal.confidence
                    else:
                        decision.confidence = fused

                    self._log_event(
                        "INFO",
                        "signal",
                        f"[COMBINED] source={final_signal.source} "
                        f"signal={final_signal.signal.value} conf={final_signal.confidence:.2f} "
                        f"(rule={rule_signal.signal.value}, ml={ml_out.signal.value} @ {ml_out.confidence:.2f})",
                        symbol=symbol,
                    )

                    ml_meta = ml_out.metadata or {}
                    decision.signals["ml_prediction"] = {
                        "signal": ml_out.signal.value,
                        "confidence": round(ml_out.confidence, 3),
                        "up": round(float(ml_meta.get("up", 0)), 3),
                        "hold": round(float(ml_meta.get("hold", 0)), 3),
                        "down": round(float(ml_meta.get("down", 0)), 3),
                    }
                    decision.signals["rule_signal"] = rule_signal.signal.value
                    decision.signals["final_source"] = final_signal.source

                    if final_signal.signal.value != decision.action.value:
                        ml_changed_final_action = True
                        decision.action = SignalAction[final_signal.signal.value]
                        decision.reason = (
                            f"[{final_signal.source.upper()}] {decision.reason}"
                        )
            else:
                decision.signals["final_source"] = (
                    "rule_only" if self.ml_enabled else "rule_only_ml_disabled"
                )

            # -------------------------------------------------------
            # Transparency: always write all five audit fields so the
            # dashboard /decisions/recent endpoint never returns nulls.
            # -------------------------------------------------------
            _final_source = decision.signals.get("final_source", "rule_only")
            _ml_pred = decision.signals.get("ml_prediction") or {}

            decision.signals["rule_signal"] = decision.signals.get(
                "rule_signal", rule_signal_value
            )
            decision.signals["ml_signal"] = _ml_pred.get("signal")  # None when ML off
            decision.signals["ml_confidence"] = _ml_pred.get("confidence")

            # combined_signal = what the pipeline ultimately decided to act on
            decision.signals["combined_signal"] = decision.action.value

            # override_reason: human-readable explanation of the pipeline outcome
            if _final_source == "ml_prioritize":
                decision.signals["override_reason"] = (
                    f"ML prioritize high confidence (>="
                    f"{getattr(self.settings, 'ml_prioritize_threshold', 0.8)}): "
                    f"{_ml_pred.get('confidence', '?')}"
                )
            elif _final_source == "ml_override":
                decision.signals["override_reason"] = (
                    f"ML override (conf={_ml_pred.get('confidence', '?')})"
                )
            elif _final_source == "combined":
                decision.signals["override_reason"] = (
                    f"Rule + ML agree on {decision.action.value}"
                )
            elif _final_source == "ml_hold_breakout":
                decision.signals["override_reason"] = (
                    f"ML directional while rules HOLD (min conf "
                    f"{getattr(self.settings, 'ml_hold_breakout_min_confidence', 0.58)}) → "
                    f"{decision.action.value}"
                )
            elif _final_source == "ml_moderate_influence":
                decision.signals["override_reason"] = (
                    f"ML moderate influence (floor–override): "
                    f"{_ml_pred.get('confidence', '?')} vs rule conflict → {decision.action.value}"
                )
            elif _final_source == "ml_rule_conflict_hold":
                decision.signals["override_reason"] = (
                    "Strict AI: rule and ML disagree — HOLD (no rule-only fallback)"
                )
            elif _final_source in ("rule_only", "rule_based"):
                if ml_out is not None and self.ml_enabled:
                    decision.signals["override_reason"] = (
                        f"ML produced {ml_out.signal.value} @ {ml_out.confidence:.2f} "
                        f"but rules retained (conflict or thresholds)"
                    )
                else:
                    decision.signals["override_reason"] = (
                        "ML signal absent or ambiguous; rule-based used"
                    )
            elif _final_source == "rule_only_ml_disabled":
                decision.signals["override_reason"] = "ML disabled"
            elif _final_source == "ml_strict_failure":
                decision.signals["override_reason"] = "AI runtime degraded — trading halted for this cycle"
            else:
                decision.signals["override_reason"] = _final_source

            self._apply_ml_audit_fields(
                decision,
                ml_context=ml_context,
                ml_out=ml_out,
                ml_infer_present=self.ml_infer is not None,
                rule_signal_value=rule_signal_value,
            )

            # Explicit ML alignment proof for each decision cycle
            decision.signals["ml_context"] = {
                "model_name": ml_context.get("model_name"),
                "symbol": ml_context.get("symbol"),
                "timeframe": ml_context.get("timeframe"),
                "model_version": ml_context.get("model_version"),
                "prediction": decision.signals.get("ml_signal"),
                "confidence": decision.signals.get("ml_confidence"),
                "ml_status": decision.signals.get("ml_status"),
                "changed_final_action": ml_changed_final_action,
                "model_dir": ml_context.get("model_dir"),
                "exact_match_exists": ml_context.get("exact_match_exists"),
                "fallback_used": ml_context.get("fallback_used"),
                "artifact_exists": ml_context.get("artifact_exists"),
                "runtime_eligible": ml_context.get("runtime_eligible"),
            }

            open_position = self._get_open_position(symbol)

            re_for_gate = bool(ml_context.get("runtime_eligible")) if self.ml_enabled else False
            if not self.ml_enabled:
                ml_ok_gate = True
            elif not re_for_gate:
                ml_ok_gate = False
            else:
                ml_ok_gate = self.ml_infer is not None and ml_out is not None
            gate_eval = evaluate_entry_gates(
                adx=float(decision.adx),
                rsi=float(decision.rsi),
                atr_pct=float(decision.atr_pct),
                ema_fast=float(decision.ema_fast),
                ema_slow=float(decision.ema_slow),
                adx_threshold=float(self.settings.adx_threshold),
                atr_vol_threshold=float(self.settings.atr_vol_threshold),
                rsi_buy_min=float(self.settings.rsi_buy_min),
                rsi_buy_max=float(self.settings.rsi_buy_max),
                ml_ok=ml_ok_gate,
                risk_ok=True,
            )
            if getattr(self.settings, "strict_entry_gates", False):
                if decision.action == SignalAction.BUY and not open_position:
                    failed = gate_eval.get("failed_gates") or []
                    if failed:
                        decision.action = SignalAction.HOLD
                        decision.reason = (
                            f"[STRICT_GATE] {failed} | {decision.reason}"
                        )

            rt_mode = resolve_runtime_mode(
                ml_enabled=self.ml_enabled,
                runtime_eligible=re_for_gate,
                model_loaded=self.ml_infer is not None,
                ml_signal_present=ml_out is not None,
                ml_error=(
                    decision.signals.get("ml_load_error")
                    or decision.signals.get("ml_prediction_error")
                ),
            ).value
            self._enrich_cycle_debug(
                decision,
                symbol=symbol,
                timeframe=timeframe,
                runtime_mode=rt_mode,
                rule_signal_value=rule_signal_value,
                ml_signal_value=ml_signal_value,
                rule_confidence_before_ml=rule_confidence_before_ml,
                has_open_position=open_position is not None,
            )
            self._attach_cycle_envelope(
                decision,
                symbol=symbol,
                timeframe=timeframe,
                runtime_mode=rt_mode,
                runtime_eligible=re_for_gate,
                rule_signal_value=rule_signal_value,
                rule_confidence_before_ml=rule_confidence_before_ml,
                ml_signal_str=decision.signals.get("ml_signal"),
                ml_conf=decision.signals.get("ml_confidence"),
                model_loaded=self.ml_infer is not None,
                feature_columns_present=feature_columns_valid(df),
                final_source=str(decision.signals.get("final_source", "rule_only")),
                open_position=open_position,
                gate_eval=gate_eval,
                ml_error=(
                    decision.signals.get("ml_load_error")
                    or decision.signals.get("ml_prediction_error")
                ),
                cooldown_blocked=False,
            )

            # Audit log: pipeline visibility for diagnostics (rule / ML / final / source)
            source = decision.signals.get("final_source", "?")
            ml_str = ml_signal_value if ml_signal_value is not None else "disabled"
            self._log_event(
                "INFO",
                "decision",
                f"DECISION_PIPELINE | RULE={rule_signal_value} | ML={ml_str} | "
                f"FINAL={decision.action.value} | SOURCE={source}",
                symbol=symbol,
            )
            self._log_event(
                "INFO",
                "decision",
                f"[FINAL] {symbol} {timeframe}: {decision.action.value} @ {current_price:.2f} "
                f"| Regime: {decision.regime.value} | Conf: {decision.confidence:.2f} | {decision.reason}",
                symbol=symbol,
            )

            if decision.action == SignalAction.SELL and open_position:
                result = self._execute_sell(
                    symbol=symbol, position=open_position, price=current_price
                )
                if not result.executed:
                    self._patch_cycle_execution_block(decision, result.reason)

                # Save decision with execution status
                decision_log = self._save_decision(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    executed=result.executed,
                    order_id=result.order_id,
                )

                return result

            if decision.action == SignalAction.BUY and not open_position:
                fs = str(decision.signals.get("final_source", ""))
                if self.ml_enabled and ml_out is not None and fs in (
                    "ml_prioritize",
                    "ml_override",
                    "combined",
                    "ml_hold_breakout",
                    "ml_moderate_influence",
                ):
                    abs_min = float(
                        getattr(self.settings, "ml_absolute_min_confidence", 0.50)
                    )
                    thr = max(
                        abs_min,
                        float(
                            getattr(self.settings, "ml_min_trade_confidence", 0.55)
                        ),
                    )
                    if float(ml_out.confidence) < abs_min:
                        decision.signals["ml_execution_gate"] = (
                            f"blocked_ml_conf_{float(ml_out.confidence):.3f}<{abs_min}"
                        )
                        self._save_decision(
                            decision, symbol, timeframe, executed=False
                        )
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason=(
                                f"ML confidence {float(ml_out.confidence):.3f} below "
                                f"ML_ABSOLUTE_MIN_CONFIDENCE ({abs_min})"
                            ),
                            price=current_price,
                        )
                    if float(ml_out.confidence) < thr:
                        decision.signals["ml_execution_gate"] = (
                            f"blocked_ml_conf_{float(ml_out.confidence):.3f}<{thr}"
                        )
                        self._save_decision(
                            decision, symbol, timeframe, executed=False
                        )
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason=(
                                f"ML confidence {float(ml_out.confidence):.3f} below "
                                f"ML_MIN_TRADE_CONFIDENCE ({thr})"
                            ),
                            price=current_price,
                        )
                adx_min = float(
                    getattr(self.settings, "ml_min_adx_for_trade", 0) or 0
                )
                if adx_min > 0 and float(decision.adx) < adx_min:
                    decision.signals["market_filter"] = "low_adx"
                    self._save_decision(decision, symbol, timeframe, executed=False)
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal="BUY",
                        reason=f"Blocked: ADX {decision.adx:.1f} < {adx_min}",
                        price=current_price,
                    )
                atr_min = float(
                    getattr(self.settings, "ml_min_atr_pct_for_trade", 0) or 0
                )
                if atr_min > 0 and float(decision.atr_pct) < atr_min:
                    decision.signals["market_filter"] = "low_volatility"
                    self._save_decision(decision, symbol, timeframe, executed=False)
                    return TradeResult(
                        success=True,
                        executed=False,
                        signal="BUY",
                        reason=f"Blocked: ATR% {decision.atr_pct:.3f} < {atr_min}",
                        price=current_price,
                    )

                effective_risk = risk_pct
                try:
                    from src.rl.hybrid import adjust_risk_for_trade

                    last_pnl: Optional[float] = None
                    try:
                        lp = (
                            self.db.query(Position)
                            .filter(
                                Position.symbol == symbol,
                                Position.mode == "live",
                                Position.is_open == False,  # noqa: E712
                            )
                            .order_by(desc(Position.exit_ts))
                            .limit(1)
                            .first()
                        )
                        if lp is not None and lp.pnl is not None:
                            last_pnl = float(lp.pnl)
                    except Exception:
                        pass

                    effective_risk, hnote = adjust_risk_for_trade(
                        self.settings,
                        self.client,
                        symbol,
                        risk_pct,
                        decision.action.value,
                        float(ml_out.confidence) if ml_out else None,
                        df,
                        last_closed_pnl=last_pnl,
                    )
                    if hnote:
                        decision.signals["hybrid_risk"] = hnote
                    if effective_risk is not None and effective_risk <= 0:
                        self._save_decision(
                            decision, symbol, timeframe, executed=False
                        )
                        return TradeResult(
                            success=True,
                            executed=False,
                            signal="BUY",
                            reason="Portfolio cap: no headroom for this asset",
                            price=current_price,
                        )
                except Exception as hy_err:
                    decision.signals["hybrid_risk_error"] = str(hy_err)[:200]

                result = self._execute_buy(
                    symbol=symbol,
                    price=current_price,
                    risk_pct=effective_risk,
                    stop_loss=decision.stop_loss,
                )
                if not result.executed:
                    self._patch_cycle_execution_block(decision, result.reason)

                # Save decision with execution status
                decision_log = self._save_decision(
                    decision=decision,
                    symbol=symbol,
                    timeframe=timeframe,
                    executed=result.executed,
                    order_id=result.order_id,
                )

                return result

            # Still save decision for transparency
            decision_log = self._save_decision(
                decision=decision,
                symbol=symbol,
                timeframe=timeframe,
                executed=False,
            )

            if open_position:
                reason = f"Position open, signal is {decision.action.value}: {decision.reason}"
            else:
                reason = (
                    f"No position, signal is {decision.action.value}: {decision.reason}"
                )

            return TradeResult(
                success=True,
                executed=False,
                signal=decision.action.value,
                reason=reason,
                price=current_price,
            )

        except Exception as e:
            self.db.rollback()
            try:
                self._persist_engine_exception_audit(
                    symbol=symbol,
                    timeframe=timeframe,
                    exc=e,
                )
            except Exception as persist_err:
                try:
                    self._log_event(
                        "ERROR",
                        "auto_trade",
                        f"Failed to persist exception audit: {persist_err}",
                        symbol=symbol,
                    )
                except Exception:
                    pass
            try:
                self._log_event(
                    "ERROR", "auto_trade", f"Error: {str(e)}", symbol=symbol
                )
            except Exception:
                pass
            return TradeResult(
                success=False, executed=False, signal="ERROR", reason=str(e)
            )

    # ---------------------------
    # Execution paths (MARKET + verify)
    # ---------------------------
    def _execute_buy(
        self,
        symbol: str,
        price: float,
        risk_pct: Optional[float],
        stop_loss: Optional[float] = None,
    ) -> TradeResult:
        balance = self._get_usdt_balance()

        # Basic safety
        if balance <= 0:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason="No USDT balance available",
                balance_before=balance,
            )

        ok_sz, _qty, spend, sz_reason = self._position_size_from_risk(
            balance=balance,
            price=price,
            stop_loss=stop_loss,
            risk_pct=risk_pct,
        )
        if not ok_sz:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"position_sizing_blocked:{sz_reason}",
                balance_before=balance,
            )

        if spend <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Calculated spend is 0",
                balance_before=balance,
            )

        try:
            f = self.client.get_symbol_filters(symbol)
            min_notional = float(f.get("minNotional") or 0)
        except Exception as e:
            self._log_event(
                "WARN", "filters", f"Failed to load symbol filters: {e}", symbol=symbol
            )
            min_notional = 0.0

        if min_notional > 0:
            # add a small buffer so rounding/fees don't undercut it
            target_spend = max(float(spend), min_notional * 1.05)
        else:
            target_spend = float(spend)

        # Can't spend more than balance
        if target_spend > balance:
            return TradeResult(
                success=True,
                executed=False,
                signal="BUY",
                reason=f"Insufficient balance for MIN_NOTIONAL. balance={balance:.2f}, "
                f"required≈{target_spend:.2f}",
                balance_before=balance,
            )

        # Binance expects quoteOrderQty with proper precision (2 decimals is usually OK for USDT)
        quote_order_qty = f"{target_spend:.2f}"
        if float(quote_order_qty) <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="quoteOrderQty rounded to 0",
                balance_before=balance,
            )

        order_response = self.client.create_order_market_buy(
            symbol=symbol,
            quote_order_qty=quote_order_qty,
        )

        order_id_raw = order_response.get("orderId")
        if order_id_raw is None:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Binance did not return orderId",
                raw_order=order_response,
                balance_before=balance,
            )

        order_id = int(order_id_raw)

        order_info = self._sync_order_status(symbol, order_id)

        executed_qty = float(order_info.get("executedQty", "0") or 0)
        cum_quote = float(order_info.get("cummulativeQuoteQty", "0") or 0)
        status = str(order_info.get("status") or "NEW")
        order_type = str(order_info.get("type") or "MARKET")

        # Record DB order with actual status/type
        self._record_order(
            symbol=symbol,
            side="BUY",
            quantity=executed_qty,
            requested_price=price,
            executed_price=price,  # better: avg fill price if you compute it; ok for Phase-1
            order_response=order_response,
            order_type=order_type,
            status=status,
        )

        if executed_qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="BUY",
                reason="Market buy returned zero executedQty",
                order_id=str(order_id),
                exchange_status=status,
                executed_qty=executed_qty,
                cummulative_quote_qty=cum_quote,
                raw_order=order_info,
                balance_before=balance,
            )

        position = self._create_position(
            symbol=symbol,
            entry_price=price,
            quantity=executed_qty,
        )

        self._log_event(
            "INFO",
            "trade",
            f"BUY(MARKET) {executed_qty:.8f} {symbol} @ {price:.2f} "
            f"(spend≈{cum_quote:.2f} USDT) status={status}",
            symbol=symbol,
        )

        return TradeResult(
            success=True,
            executed=True,
            signal="BUY",
            reason="Market buy executed + verified",
            order_id=str(order_id),
            price=price,
            quantity=executed_qty,
            balance_before=balance,
            balance_after=balance - float(cum_quote or target_spend),
            position_id=position.id,
            exchange_status=status,
            executed_qty=executed_qty,
            cummulative_quote_qty=cum_quote,
            raw_order=order_info,
        )

    def _execute_sell(
        self, symbol: str, position: Position, price: float
    ) -> TradeResult:
        qty = float(position.entry_qty or 0)

        if qty <= 0:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Position has invalid quantity",
                position_id=position.id,
            )

        order_response = self.client.create_order_market_sell(
            symbol=symbol,
            quantity=f"{qty:.8f}",
        )

        order_id_raw = order_response.get("orderId")
        if order_id_raw is None:
            return TradeResult(
                success=False,
                executed=False,
                signal="SELL",
                reason="Binance did not return orderId",
                raw_order=order_response,
                position_id=position.id,
            )

        order_id = int(order_id_raw)

        order_info = self._sync_order_status(symbol, order_id)

        executed_qty = float(order_info.get("executedQty", "0") or 0)
        cum_quote = float(order_info.get("cummulativeQuoteQty", "0") or 0)
        status = str(order_info.get("status") or "NEW")
        order_type = str(order_info.get("type") or "MARKET")

        self._record_order(
            symbol=symbol,
            side="SELL",
            quantity=executed_qty,
            requested_price=price,
            executed_price=price,
            order_response=order_response,
            order_type=order_type,
            status=status,
        )

        # Close position using executed qty if available, otherwise fallback
        self._close_position(position, price, executed_qty or qty)

        # cooldown after loss
        if position.pnl is not None and position.pnl < 0:
            self.cooldown.trigger(
                datetime.utcnow(),
                self.risk_config.cooldown_minutes_after_loss,
            )
            self._log_event(
                "WARN",
                "trade",
                f"Loss trade - cooldown for {self.risk_config.cooldown_minutes_after_loss} min",
                symbol=symbol,
            )

        pnl_val = position.pnl if position.pnl is not None else 0.0
        pnl_pct = position.pnl_pct if position.pnl_pct is not None else 0.0

        self._log_event(
            "INFO",
            "trade",
            f"SELL(MARKET) {executed_qty:.8f} {symbol} @ {price:.2f} "
            f"(recv≈{cum_quote:.2f} USDT) status={status} P&L={pnl_val:.2f} ({pnl_pct:.2f}%)",
            symbol=symbol,
        )

        return TradeResult(
            success=True,
            executed=True,
            signal="SELL",
            reason=f"Market sell executed + verified (P&L: {pnl_pct:.2f}%)",
            order_id=str(order_id),
            price=price,
            quantity=executed_qty,
            position_id=position.id,
            exchange_status=status,
            executed_qty=executed_qty,
            cummulative_quote_qty=cum_quote,
            raw_order=order_info,
        )
