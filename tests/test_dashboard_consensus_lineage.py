from __future__ import annotations

from fastapi.testclient import TestClient

from gungnir.persistence.db import Database


def test_consensus_evidence_endpoint_returns_joined_lifecycle(monkeypatch, tmp_path):
    db_path = tmp_path / "gungnir.db"
    db = Database(db_path)
    db.record_consensus_lifecycle(
        decision_id="decision-1", experiment_id="test", ts="2026-07-23T00:00:00+00:00",
        symbol="US100", analytical_action="enter", analytical_reason="entry_threshold",
        side="buy", book="consensus_shadow", feed_provenance="synthetic",
        config_snapshot_hash="cfg", strategy_registry_hash="registry", code_version="test",
        diagnostics={"votes": [{"strategy_id": "trend"}]},
    )
    monkeypatch.setenv("GUNGNIR_DB_PATH", str(db_path))
    from gungnir.dashboard.server import create_app

    response = TestClient(create_app()).get("/api/consensus/evidence?limit=10")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["decision_id"] == "decision-1"
    assert item["analytical_action"] == "enter"
    assert item["diagnostics"]["votes"][0]["strategy_id"] == "trend"
