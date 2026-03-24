from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import json
import os

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.db.models import EventLog, Order, Position, TradingDecisionLog
from src.exchange.binance_spot_client import BinanceSpotClient
from src.risk.rules import CooldownState, RiskConfig
from src.features.indicators import add_all_indicators
from src.live.adaptive_strategy import AdaptiveStrategy, TradingDecision, SignalAction
from src.live.fully_adaptive_strategy import FullyAdaptiveStrategy
from src.ml.model_selector import resolve_model_selection


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
            confidence=decision.confidence,
            symbol=symbol,
            timeframe=timeframe,
            regime=decision.regime.value,
            price=decision.price,
            ts=datetime.utcnow(),
            adx=decision.adx,
            ema_fast=decision.ema_fast,
            ema_slow=decision.ema_slow,
            rsi=decision.rsi,
            bb_upper=decision.bb_upper,
            bb_lower=decision.bb_lower,
            atr=decision.atr,
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            risk_reward=decision.risk_reward,
            reason=decision.reason,
            signals_json=json.dumps(decision.signals),
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
        try:
            result = self.ml_infer.predict_window(df)

            # NOTE: inference.py returns _CLASSES = ["SELL","HOLD","BUY"]
            # so result["signal"] is "BUY", "SELL", or "HOLD" — NOT "up"/"down"
            raw_signal = str(result.get("signal", "HOLD")).upper()
            if raw_signal == "BUY":
                sig = SignalType.BUY
            elif raw_signal == "SELL":
                sig = SignalType.SELL
            else:
                sig = SignalType.HOLD

            # Log detailed ML prediction probabilities for transparency
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
        except Exception as e:
            self._log_event("ERROR", "ml", f"ML prediction failed: {e}")
            return None

    def _combine_signals(
        self, rule_signal: TradeSignal, ml_signal: Optional[TradeSignal]
    ) -> TradeSignal:
        if not ml_signal:
            return rule_signal

        override_th = float(getattr(self.settings, "ml_override_threshold", 0.95))
        agree_th = float(getattr(self.settings, "ml_agree_threshold", 0.70))

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

        self._log_event(
            "INFO",
            "signal",
            f"Signal conflict - using rule-based: {rule_signal.signal.value}",
        )
        return rule_signal

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

    # ---------------------------
    # Main entry
    # ---------------------------

    def execute_auto_trade(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        risk_pct: Optional[float] = None,
        force_signal: Optional[str] = None,  # "BUY" | "SELL"
    ) -> TradeResult:
        now = datetime.utcnow()

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

            self.ml_infer = None
            if self.ml_enabled:
                try:
                    if ml_context.get("model_exists"):
                        from src.ml.inference import get_infer

                        self.ml_infer = get_infer(str(ml_context["model_dir"]))
                    else:
                        decision.signals["ml_load_error"] = "model_not_found"
                except Exception as e:
                    decision.signals["ml_load_error"] = str(e)
                    self.ml_infer = None

            if self.ml_infer:
                ml_signal = self._generate_ml_signal(df)
                if ml_signal:
                    ml_signal_value = ml_signal.signal.value
                    rule_signal = TradeSignal(
                        signal=SignalType[decision.action.value],
                        confidence=decision.confidence,
                        price=decision.price,
                        timestamp=datetime.utcnow(),
                        source="rule_based",
                    )
                    final_signal = self._combine_signals(rule_signal, ml_signal)

                    # Log combined result
                    self._log_event(
                        "INFO",
                        "signal",
                        f"[COMBINED] source={final_signal.source} "
                        f"signal={final_signal.signal.value} conf={final_signal.confidence:.2f} "
                        f"(rule={rule_signal.signal.value}, ml={ml_signal.signal.value} @ {ml_signal.confidence:.2f})",
                        symbol=symbol,
                    )

                    # Enrich signals dict with ML data for full transparency in DB/dashboard
                    ml_meta = ml_signal.metadata or {}
                    decision.signals["ml_prediction"] = {
                        "signal": ml_signal.signal.value,
                        "confidence": round(ml_signal.confidence, 3),
                        "up": round(float(ml_meta.get("up", 0)), 3),
                        "hold": round(float(ml_meta.get("hold", 0)), 3),
                        "down": round(float(ml_meta.get("down", 0)), 3),
                    }
                    decision.signals["rule_signal"] = rule_signal.signal.value
                    decision.signals["final_source"] = final_signal.source

                    # If ML changed the action, update the decision
                    if final_signal.signal.value != decision.action.value:
                        ml_changed_final_action = True
                        decision.action = SignalAction[final_signal.signal.value]
                        decision.confidence = final_signal.confidence
                        decision.reason = (
                            f"[{final_signal.source.upper()}] {decision.reason}"
                        )
                    else:
                        # Boost confidence when both agree
                        decision.confidence = max(
                            decision.confidence, final_signal.confidence
                        )
                else:
                    decision.signals["final_source"] = "rule_only"
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
            if _final_source == "ml_override":
                decision.signals["override_reason"] = (
                    f"ML override (conf={_ml_pred.get('confidence', '?')})"
                )
            elif _final_source == "combined":
                decision.signals["override_reason"] = (
                    f"Rule + ML agree on {decision.action.value}"
                )
            elif _final_source == "rule_only":
                decision.signals["override_reason"] = (
                    "ML signal absent or ambiguous; rule-based used"
                )
            elif _final_source == "rule_only_ml_disabled":
                decision.signals["override_reason"] = "ML disabled"
            else:
                decision.signals["override_reason"] = _final_source

            # Explicit ML alignment proof for each decision cycle
            decision.signals["ml_context"] = {
                "model_name": ml_context.get("model_name"),
                "symbol": ml_context.get("symbol"),
                "timeframe": ml_context.get("timeframe"),
                "model_version": ml_context.get("model_version"),
                "prediction": decision.signals.get("ml_signal"),
                "confidence": decision.signals.get("ml_confidence"),
                "changed_final_action": ml_changed_final_action,
                "model_dir": ml_context.get("model_dir"),
                "model_exists": ml_context.get("model_exists"),
                "specific_match": ml_context.get("specific_match"),
            }

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

            open_position = self._get_open_position(symbol)

            if decision.action == SignalAction.SELL and open_position:
                result = self._execute_sell(
                    symbol=symbol, position=open_position, price=current_price
                )

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
                result = self._execute_buy(
                    symbol=symbol, price=current_price, risk_pct=risk_pct
                )

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
        self, symbol: str, price: float, risk_pct: Optional[float]
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

        # Determine spend from risk
        _, spend = self._calculate_position_size(balance, price, risk_pct)

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
