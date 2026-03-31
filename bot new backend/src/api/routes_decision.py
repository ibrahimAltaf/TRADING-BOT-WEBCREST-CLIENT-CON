"""Decision observability: latest cycle + recent logs (parsed envelope when present)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy import desc

from src.db.models import TradingDecisionLog
from src.db.session import SessionLocal

router = APIRouter(prefix="/decision", tags=["decision"])


def _parse_signals_json(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"parse_error": true, "raw_preview": (raw or "")[:200]}


@router.get("/latest")
def decision_latest() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        row = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .first()
        )
        if not row:
            return {"ok": False, "error": "no_decisions"}
        sig = _parse_signals_json(getattr(row, "signals_json", None))
        return {
            "ok": True,
            "ts": row.ts.isoformat() if row.ts else None,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "action": row.action,
            "confidence": row.confidence,
            "reason": row.reason,
            "executed": bool(row.executed),
            "cycle_envelope": sig.get("cycle_envelope"),
            "cycle_debug": sig.get("cycle_debug"),
        }
    finally:
        db.close()


@router.get("/logs")
def decision_logs(limit: int = 50) -> Dict[str, Any]:
    """Recent decision rows (newest first) with envelope + cycle_debug when present."""
    lim = max(1, min(200, int(limit)))
    db = SessionLocal()
    try:
        rows = (
            db.query(TradingDecisionLog)
            .order_by(desc(TradingDecisionLog.ts))
            .limit(lim)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            sig = _parse_signals_json(getattr(row, "signals_json", None))
            out.append(
                {
                    "ts": row.ts.isoformat() if row.ts else None,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "action": row.action,
                    "confidence": row.confidence,
                    "reason": (row.reason or "")[:2000],
                    "executed": bool(row.executed),
                    "cycle_envelope": sig.get("cycle_envelope"),
                    "cycle_debug": sig.get("cycle_debug"),
                }
            )
        return {"ok": True, "count": len(out), "items": out}
    finally:
        db.close()
