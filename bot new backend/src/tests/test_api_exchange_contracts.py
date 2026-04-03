"""
Contract tests for exchange observability APIs using an isolated in-memory SQLite DB.

Run many times (e.g. 15x) in CI or locally: pytest src/tests/test_api_exchange_contracts.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_exchange
from src.api import routes_status
from src.db.base import Base
from src.db.models import EventLog, TradingDecisionLog
import src.db.models  # noqa: F401 — register models
from src.main import app


@pytest.fixture
def memory_session_factory():
    # StaticPool: all connections share one :memory: DB (default :memory: is per-connection).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    return factory


@pytest.fixture
def patched_session(memory_session_factory):
    """Route modules keep their own SessionLocal reference; patch both + db.session."""
    import src.db.session as db_session

    orig = db_session.SessionLocal
    db_session.SessionLocal = memory_session_factory
    routes_exchange.SessionLocal = memory_session_factory
    routes_status.SessionLocal = memory_session_factory

    yield memory_session_factory

    db_session.SessionLocal = orig
    routes_exchange.SessionLocal = orig
    routes_status.SessionLocal = orig


@pytest.fixture
def client(patched_session):
    return TestClient(app)


def _decision_row(
    *,
    symbol: str,
    ts: datetime,
    final_source: str,
    hold_kind: str | None = None,
    runtime_mode: str = "ai_active",
) -> TradingDecisionLog:
    signals = {
        "final_source": final_source,
        "rule_signal": "HOLD",
        "ml_signal": None,
        "cycle_debug": {
            "runtime_mode": runtime_mode,
            "hold_kind": hold_kind,
        },
    }
    return TradingDecisionLog(
        action="HOLD",
        confidence=0.5,
        symbol=symbol,
        timeframe="1h",
        regime="RANGING",
        price=100.0,
        ts=ts,
        reason="test",
        signals_json=json.dumps(signals),
        executed=False,
    )


class TestDecisionsRecentContract:
    def test_symbol_filter_is_case_insensitive(self, client, patched_session):
        db = patched_session()
        base = datetime(2025, 1, 1, 12, 0, 0)
        db.add(_decision_row(symbol="BTCUSDT", ts=base, final_source="rule_only"))
        db.add(
            _decision_row(
                symbol="ETHUSDT",
                ts=base + timedelta(minutes=1),
                final_source="ml_strict_failure",
            )
        )
        db.commit()
        db.close()

        r = client.get("/exchange/decisions/recent?symbol=btcusdt&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["count"] == 1
        assert data["decisions"][0]["symbol"] == "BTCUSDT"
        assert data["decisions"][0]["final_source"] == "rule_only"

    def test_final_source_surfaces_engine_exception(self, client, patched_session):
        db = patched_session()
        db.add(
            _decision_row(
                symbol="SOLUSDT",
                ts=datetime(2025, 1, 2, 12, 0, 0),
                final_source="engine_exception",
            )
        )
        db.commit()
        db.close()

        r = client.get("/exchange/decisions/recent?symbol=SOLUSDT&limit=5")
        assert r.status_code == 200
        d = r.json()["decisions"][0]
        assert d["final_source"] == "engine_exception"
        assert d.get("cycle_debug", {}).get("runtime_mode") == "ai_active"


class TestLogsRecentContract:
    def test_symbol_scope_filters_rows(self, client, patched_session):
        db = patched_session()
        t = datetime(2025, 1, 3, 10, 0, 0)
        db.add(
            EventLog(
                level="INFO",
                category="decision",
                message="eth",
                ts=t,
                symbol="ETHUSDT",
            )
        )
        db.add(
            EventLog(
                level="INFO",
                category="decision",
                message="btc",
                ts=t + timedelta(seconds=1),
                symbol="BTCUSDT",
            )
        )
        db.commit()
        db.close()

        r = client.get("/exchange/logs/recent?symbol=ETHUSDT&limit=20")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["scope"] == "ETHUSDT"
        msgs = [x["message"] for x in data["logs"]]
        assert "eth" in msgs
        assert "btc" not in msgs


class TestAiObservabilityContract:
    def test_response_shape_and_entropy(self, client, patched_session):
        db = patched_session()
        base = datetime(2025, 1, 4, 8, 0, 0)
        for i, fs in enumerate(["rule_only", "ml_strict_failure", "rule_only"]):
            db.add(
                _decision_row(
                    symbol="BTCUSDT",
                    ts=base + timedelta(minutes=i),
                    final_source=fs,
                    runtime_mode="ai_degraded" if fs == "ml_strict_failure" else "ai_active",
                )
            )
        db.commit()
        db.close()

        r = client.get("/exchange/performance/ai-observability?symbol=BTCUSDT&limit=100")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["symbol_filter"] == "BTCUSDT"
        assert data["sample_size"] == 3
        assert "ml_usage" in data and "pct_with_ml_signal" in data["ml_usage"]
        assert "runtime_posture" in data
        rp = data["runtime_posture"]
        assert rp["degraded_or_unavailable_cycles"] >= 1
        assert rp["ml_strict_failure_cycles"] >= 1
        assert data["decision_diversity"]["final_source_entropy_bits"] > 0
        assert "final_source_counts" in data
        assert data["final_source_counts"].get("ml_strict_failure", 0) >= 1


def test_latest_decision_normalizes_symbol(client, patched_session):
    db = patched_session()
    db.add(
        _decision_row(
            symbol="BTCUSDT",
            ts=datetime(2025, 1, 5, 1, 0, 0),
            final_source="rule_only",
        )
    )
    db.commit()
    db.close()

    r = client.get("/exchange/decisions/latest?symbol=btcusdt")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["decision"]["symbol"] == "BTCUSDT"
    assert body["decision"]["final_source"] == "rule_only"
