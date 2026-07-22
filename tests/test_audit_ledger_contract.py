"""Regression contract for immutable execution/audit lineage."""

from __future__ import annotations

import sqlite3

from gungnir.backtest.costs import CostModel
from gungnir.persistence.db import Database


def test_cost_model_emits_versioned_audit_snapshot():
    model = CostModel(spread_bps=12.5, commission_bps=1.2, slippage_bps=3.0)
    snapshot = model.audit_snapshot(validation_status="unvalidated")
    assert snapshot["version"] == "cost-model-v1"
    assert snapshot["spread_bps"] == 12.5
    assert snapshot["validation_status"] == "unvalidated"
    assert len(snapshot["fingerprint"]) == 64


def test_execution_ledger_persists_intent_fill_and_reconciliation(tmp_path):
    db = Database(tmp_path / "audit.db")
    client_id = "signal-1"
    db.record_order_intent(
        client_id=client_id, signal_id="signal-1", ts="2026-07-22T00:00:00+00:00",
        symbol="EURUSD", side="buy", intended_size=1.0, mode="shadow",
        decision_price=1.1, cost_model={"version": "cost-model-v1"},
    )
    db.record_execution_event(
        client_id=client_id, event_type="FILL", ts="2026-07-22T00:00:01+00:00",
        broker_id="paper:signal-1", payload={"fill_price": 1.1002},
    )
    db.record_reconciliation_event(
        client_id=client_id, ts="2026-07-22T00:00:02+00:00",
        source="internal", status="pending_external", detail={"reason": "awaiting_broker"},
    )

    intent = db.conn.execute("SELECT * FROM order_intents WHERE client_id=?", (client_id,)).fetchone()
    fill = db.conn.execute("SELECT * FROM execution_events WHERE client_id=?", (client_id,)).fetchone()
    reconciliation = db.conn.execute("SELECT * FROM reconciliation_events WHERE client_id=?", (client_id,)).fetchone()
    assert intent["cost_model"] == '{"version": "cost-model-v1"}'
    assert fill["broker_id"] == "paper:signal-1"
    assert reconciliation["status"] == "pending_external"


def test_ledger_migration_preserves_existing_trade_table(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
        side TEXT NOT NULL, volume REAL NOT NULL, entry_price REAL NOT NULL, exit_price REAL,
        pnl REAL, strategy TEXT, mode TEXT DEFAULT 'real', opened_at TEXT NOT NULL,
        closed_at TEXT, context TEXT)""")
    conn.commit(); conn.close()
    db = Database(path)
    assert db.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    assert {"order_intents", "execution_events", "reconciliation_events"} <= {
        row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_closed_trade_writes_execution_and_reconciliation_events(tmp_path):
    from datetime import datetime, timezone
    from gungnir.data.models import Side, Trade
    from gungnir.learning.journal import Journal

    journal = Journal(Database(tmp_path / "closed.db"))
    journal.record(Trade(symbol="EURUSD", side=Side.BUY, volume=1.0,
                         entry_price=1.1, exit_price=1.11, pnl=0.01, mode="shadow",
                         opened_at=datetime.now(timezone.utc), closed_at=datetime.now(timezone.utc),
                         context={"client_id": "signal-closed", "deal_id": "paper:signal-closed"}))
    assert journal.db.conn.execute("SELECT event_type FROM execution_events").fetchone()[0] == "CLOSE"
    assert journal.db.conn.execute("SELECT status FROM reconciliation_events").fetchone()[0] == "pending_external"
