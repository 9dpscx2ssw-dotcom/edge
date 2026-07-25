"""Backtests should prefer real cached market data (data/gungnir.db's
`candles` table, populated by the live agent's fast loop) over a live
Capital.com fetch or a synthetic random walk — no credentials or network
round-trip required, and reproducible run to run.

Covers `_backtest_candles`'s new source precedence directly and through
`POST /api/backtest/run`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from gungnir.data.models import Candle
from gungnir.persistence.db import Database


def _seed_candles(db_path, symbol="EURUSD", timeframe="1h", n=150):
    db = Database(db_path)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(symbol=symbol, timeframe=timeframe, open=1.10 + 0.0001 * i,
              high=1.1005 + 0.0001 * i, low=1.0995 + 0.0001 * i,
              close=1.1002 + 0.0001 * i, volume=1000,
              ts=start + timedelta(hours=i))
        for i in range(n)
    ]
    db.store_candles(candles)
    db.close()


def test_backtest_candles_prefers_cached_db(tmp_path, monkeypatch):
    db_path = tmp_path / "g.db"
    _seed_candles(db_path)
    monkeypatch.setenv("GUNGNIR_DB_PATH", str(db_path))

    from gungnir.dashboard.server import _backtest_candles

    candles, source = _backtest_candles("EURUSD", 100, "1h")
    assert source == "cached_db"
    assert len(candles) >= 80
    assert candles[0].symbol == "EURUSD"


def test_backtest_candles_falls_back_when_cache_too_thin(tmp_path, monkeypatch):
    db_path = tmp_path / "g.db"
    _seed_candles(db_path, n=10)   # below the 80-bar warm-up floor
    monkeypatch.setenv("GUNGNIR_DB_PATH", str(db_path))

    from gungnir.dashboard.server import _backtest_candles

    candles, source = _backtest_candles("EURUSD", 100, "1h")
    assert source == "synthetic"   # no creds configured in the test env
    assert len(candles) > 0


def test_backtest_run_endpoint_reports_cached_db_source(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    db_path = tmp_path / "g.db"
    _seed_candles(db_path, symbol="US500", n=150)
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({
        "mode": "dry-run", "balance": 10000, "equity": 10000, "running_pl": 0,
        "closed_pl": 0, "trade_counts": {"real": 0, "shadow": 0}, "views": {},
        "strategies": [], "macro": [], "news": [],
    }))
    monkeypatch.setenv("GUNGNIR_DB_PATH", str(db_path))
    monkeypatch.setenv("GUNGNIR_STATUS_PATH", str(status_path))
    monkeypatch.setenv("GUNGNIR_CONTROL_PATH", str(tmp_path / "control.json"))
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-dashboard-token")

    from gungnir.dashboard.server import create_app

    c = TestClient(create_app())
    resp = c.post("/api/backtest/run", json={
        "symbol": "US500", "timeframe": "1h", "lookback_days": 5, "strategies": [1],
    }, headers={"X-Dashboard-Token": "test-dashboard-token"})
    assert resp.status_code == 200
    assert resp.json()["data_source"] == "cached_db"
