from __future__ import annotations

from datetime import datetime, timezone

from gungnir.data.models import Side
from gungnir.persistence.db import Database


def _row(db: Database, decision_id: str) -> dict:
    row = db.conn.execute(
        "SELECT * FROM consensus_lifecycle WHERE decision_id=?", (decision_id,)
    ).fetchone()
    assert row is not None
    return dict(row)


def test_consensus_lifecycle_preserves_immutable_decision_and_terminal_outcome(tmp_path):
    db = Database(tmp_path / "journal.db")
    db.record_consensus_lifecycle(
        decision_id="d-1", experiment_id="consensus-shadow-parallel-cap-v2",
        ts=datetime(2026, 7, 23, tzinfo=timezone.utc).isoformat(), symbol="US100",
        analytical_action="enter", analytical_reason="entry_threshold",
        side="buy", book="consensus_shadow", feed_provenance="synthetic",
        config_snapshot_hash="cfg", strategy_registry_hash="registry",
        code_version="test", diagnostics={"votes": []},
    )
    db.update_consensus_lifecycle("d-1", terminal_state="opened_shadow", client_id="c-1")
    db.update_consensus_lifecycle("d-1", terminal_state="closed", trade_id="42", realised_pnl=-1.25)

    row = _row(db, "d-1")
    assert row["experiment_id"] == "consensus-shadow-parallel-cap-v2"
    assert row["terminal_state"] == "closed"
    assert row["client_id"] == "c-1"
    assert row["trade_id"] == "42"
    assert row["realised_pnl"] == -1.25


def test_consensus_lifecycle_rejects_terminal_state_rewrite(tmp_path):
    db = Database(tmp_path / "journal.db")
    db.record_consensus_lifecycle(
        decision_id="d-2", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", analytical_action="none", analytical_reason="below_entry",
        side=None, book="consensus_shadow", feed_provenance="synthetic",
        config_snapshot_hash="cfg", strategy_registry_hash="registry", code_version="test",
        diagnostics={},
    )
    db.update_consensus_lifecycle("d-2", terminal_state="not_submitted")
    try:
        db.update_consensus_lifecycle("d-2", terminal_state="opened_shadow")
    except ValueError as exc:
        assert "terminal" in str(exc)
    else:
        raise AssertionError("terminal lifecycle rewrite must fail")


def test_consensus_lifecycle_exposes_read_only_evidence(tmp_path):
    db = Database(tmp_path / "journal.db")
    db.record_consensus_lifecycle(
        decision_id="d-3", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", analytical_action="veto", analytical_reason="opposition",
        side=Side.BUY.value, book="consensus_shadow", feed_provenance="synthetic",
        config_snapshot_hash="cfg", strategy_registry_hash="registry", code_version="test",
        diagnostics={"votes": [{"strategy_id": "a"}]},
    )
    result = db.recent_consensus_evidence(limit=1)
    assert result[0]["decision_id"] == "d-3"
    assert result[0]["diagnostics"]["votes"][0]["strategy_id"] == "a"


def test_consensus_signal_persists_decision_foreign_key(tmp_path):
    from gungnir.data.models import Signal

    db = Database(tmp_path / "journal.db")
    signal = Signal(strategy="consensus", symbol="US100", side=Side.BUY, conviction=0.8)
    db.record_signal(signal, "shadow", 100.0, decision_id="d-signal")
    row = db.conn.execute("SELECT decision_id FROM signals").fetchone()
    assert row["decision_id"] == "d-signal"



def test_consensus_verdict_write_is_atomic(tmp_path):
    db = Database(tmp_path / "journal.db")
    db.record_consensus_verdict(
        decision_id="atomic-1", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", action="enter", side="buy", score=0.5, opposing=0.1,
        stance_count=2, disposition="enter", analytical_reason="entry_threshold",
        book="consensus_shadow", feed_provenance="synthetic", config_snapshot_hash="cfg",
        strategy_registry_hash="registry", code_version="test", diagnostics={"votes": []},
    )
    assert db.conn.execute("SELECT COUNT(*) FROM consensus_decisions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM consensus_lifecycle").fetchone()[0] == 1


def test_consensus_lifecycle_rejects_impossible_transition(tmp_path):
    db = Database(tmp_path / "journal.db")
    db.record_consensus_lifecycle(
        decision_id="d-invalid", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", analytical_action="enter", analytical_reason="entry_threshold",
        side="buy", book="consensus_shadow", feed_provenance="synthetic",
        config_snapshot_hash="cfg", strategy_registry_hash="registry", code_version="test",
        diagnostics={},
    )
    try:
        db.update_consensus_lifecycle("d-invalid", terminal_state="closed")
    except ValueError as exc:
        assert "invalid consensus lifecycle transition" in str(exc)
    else:
        raise AssertionError("pending lifecycle cannot close without an opening")


def test_consensus_evidence_joins_decision_and_signal_branch(tmp_path):
    from gungnir.data.models import Signal

    db = Database(tmp_path / "journal.db")
    db.record_consensus_verdict(
        decision_id="joined-1", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", action="enter", side="buy", score=0.5, opposing=0.1,
        stance_count=2, disposition="enter", analytical_reason="entry_threshold",
        book="consensus_shadow", feed_provenance="synthetic", config_snapshot_hash="cfg",
        strategy_registry_hash="registry", code_version="test", diagnostics={"votes": []},
    )
    db.record_signal(
        Signal(strategy="consensus", symbol="US100", side=Side.BUY, conviction=0.8),
        "shadow", 100.0, client_id="client-1", decision_id="joined-1",
    )
    db.update_consensus_lifecycle("joined-1", terminal_state="opened_shadow", client_id="client-1")
    item = db.recent_consensus_evidence(limit=1)[0]
    assert item["decision"]["decision_id"] == "joined-1"
    assert item["signal"]["client_id"] == "client-1"
    assert item["signal"]["disposition"] == "shadow"



def test_consensus_evidence_joins_trade_branch(tmp_path):
    from gungnir.data.models import Trade

    db = Database(tmp_path / "journal.db")
    db.record_consensus_verdict(
        decision_id="trade-joined-1", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", action="enter", side="buy", score=0.5, opposing=0.1,
        stance_count=2, disposition="enter", analytical_reason="entry_threshold",
        book="consensus_shadow", feed_provenance="synthetic", config_snapshot_hash="cfg",
        strategy_registry_hash="registry", code_version="test", diagnostics={"votes": []},
    )
    db.update_consensus_lifecycle("trade-joined-1", terminal_state="opened_shadow", client_id="client-2")
    trade_id = db.record_trade(Trade(symbol="US100", side=Side.BUY, volume=1.0,
        entry_price=100.0, exit_price=101.0, pnl=1.0, strategy="consensus",
        mode="shadow", context={"client_id": "client-2", "decision_id": "trade-joined-1"}))
    db.update_consensus_lifecycle("trade-joined-1", terminal_state="closed", trade_id=str(trade_id), realised_pnl=1.0)
    item = db.recent_consensus_evidence(limit=1)[0]
    assert item["trade"]["id"] == trade_id
    assert item["trade"]["pnl"] == 1.0
