"""Every strategy added/rebuilt this session (plus consensus) must appear on
the INSTRUMENT x STRATEGY heatmap on both the Strategies tab (/api/strategies,
registry-driven — shows up immediately, even with zero trades) and the
Report tab (learning/reports.py::_matrix, trade-driven — shows up once it
has closed trades). Both are already data/registry-driven rather than using
a hardcoded strategy list, so a new KRAKEN_STRATEGIES entry is picked up
automatically; this guards that assumption against regressing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from gungnir.data.models import Side, Trade
from gungnir.learning.reports import _matrix
from gungnir.persistence.db import Database
from gungnir.strategy.registry import _REGISTRY

NEW_STRATEGIES = [
    "bb_macd_sma_app", "cci200_ema_pivot_app", "bb_rsi_m30", "multi_bb_app",
    "parsar_cci_ema_m1", "parsar_cci_ema_m5", "ao_macd_app",
    "follow_the_trend_h4", "follow_the_trend_d1", "goldmine_xauusd",
    "speculative_zigzag_rsi", "bb_rsi_cutting",
    # Final app-spec batch (25 Jul).
    "parsar_awesome", "cci_ema_psar", "ema_adx_macd_contrarian", "momentum_forex",
    "psar_ao_ac", "cci_ema_fixed", "ema100_dual_tf", "ichimoku_awesome",
    "scalp_macd_stoch_10pt", "ema200_awesome", "bb_williams_rsi_ranging", "triple_sma",
]


def test_new_strategies_are_all_registered():
    for name in NEW_STRATEGIES:
        assert name in _REGISTRY, f"{name} missing from the strategy registry"


def test_strategies_tab_matrix_includes_new_strategies_and_consensus(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    db_path = tmp_path / "g.db"
    status_path = tmp_path / "status.json"
    Database(db_path).close()
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
    resp = c.get("/api/strategies")
    assert resp.status_code == 200
    body = resp.json()

    reported_names = {s["name"] for s in body["strategies"]}
    matrix_names = {s["name"] for s in body["instrument_strategy"]["strategies"]}

    assert "consensus" in reported_names
    assert "consensus" in matrix_names
    for name in NEW_STRATEGIES:
        assert name in reported_names, f"{name} missing from the strategy list"
        assert name in matrix_names, f"{name} missing from the instrument x strategy matrix axis"


def test_report_matrix_picks_up_a_new_strategys_trades_and_consensus():
    now = datetime.now(timezone.utc)

    def _trade(strategy, symbol, pnl):
        return Trade(
            symbol=symbol, strategy=strategy, side=Side.BUY, volume=1.0,
            entry_price=100.0, exit_price=100.0 + pnl, pnl=pnl,
            opened_at=now - timedelta(minutes=10), closed_at=now,
        )

    trades = [
        _trade("goldmine_xauusd", "GOLD", 12.5),
        _trade("follow_the_trend_h4", "EURUSD", -4.0),
        _trade("consensus", "US100", 30.0),
        _trade("triple_sma", "EURUSD", 8.0),
        _trade("ema100_dual_tf", "GBPUSD", -2.5),
    ]
    m = _matrix(trades)
    assert "goldmine_xauusd" in m["strategies"]
    assert "follow_the_trend_h4" in m["strategies"]
    assert "consensus" in m["strategies"]
    assert "triple_sma" in m["strategies"]
    assert "ema100_dual_tf" in m["strategies"]
    assert "GOLD" in m["instruments"]
