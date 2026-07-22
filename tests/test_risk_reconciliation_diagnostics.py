"""Regression coverage for broker reconciliation and actionable risk vetoes."""

from __future__ import annotations

from gungnir.config import Config, Secrets
from gungnir.data.models import Side, Signal, Trade
from gungnir.persistence.db import Database
from gungnir.risk.portfolio import PortfolioRisk


def _risk(**raw) -> PortfolioRisk:
    r = PortfolioRisk(Config({"risk": raw}, Secrets.from_env()))
    r.equity = 10_000.0
    r.day_start_equity = 10_000.0
    return r


def _signal(symbol="US100") -> Signal:
    return Signal(strategy="consensus", symbol=symbol, side=Side.BUY, conviction=0.8)


def test_position_cap_rejection_has_actionable_machine_readable_detail():
    risk = _risk(max_open_positions=2)
    risk.open_exposure = {"AAA": 100.0, "BBB": 200.0}

    assert risk.vet(_signal(), raw_volume=1, price=100, atr=1) is None
    assert risk.last_rejection == {
        "rule": "max_open_positions",
        "current": 2,
        "limit": 2,
        "symbol": "US100",
        "book": "real",
    }


def test_shadow_exposure_is_isolated_from_adopted_real_positions():
    risk = _risk(max_portfolio_exposure=0.5, max_per_asset_exposure=0.5)
    # Adopted broker positions may exhaust the real account's capacity, but they
    # must not consume the separately capped internal Shadow learning book.
    risk.set_open_exposure("real", {"GOLD": 20_000.0})
    risk.update_book("shadow", 10_000.0)
    risk.set_open_exposure("shadow", {})

    shadow_order = risk.vet(_signal("NVDA"), raw_volume=1, price=100, atr=1, book="shadow")
    assert shadow_order is not None, risk.last_rejection
    assert risk.vet(_signal("NVDA"), raw_volume=1, price=100, atr=1, book="real") is None
    assert risk.last_rejection["rule"] == "exposure_cap"


def test_signal_journal_preserves_risk_rejection_reason_and_detail(tmp_path):
    db = Database(tmp_path / "journal.db")
    try:
        db.record_signal(
            _signal(), "rejected_risk", 100.0,
            rejection_reason="max_open_positions",
            rejection_detail={"current": 14, "limit": 14, "symbol": "US100"},
        )
        row = db.recent_signals(1)[0]
        assert row["rejection_reason"] == "max_open_positions"
        assert row["rejection_detail"] == {"current": 14, "limit": 14, "symbol": "US100"}
    finally:
        db.close()


def test_broker_snapshot_separates_adopted_from_attributed_and_uses_account_pnl():
    from gungnir.core.reconciliation import broker_snapshot

    positions = [
        Trade(symbol="US100", side=Side.BUY, volume=1, entry_price=20_000,
              strategy="consensus", context={"deal_id": "a"}),
        Trade(symbol="NVDA", side=Side.SELL, volume=2, entry_price=200,
              strategy="", context={"deal_id": "b", "adopted": True}),
    ]
    snapshot = broker_snapshot(positions, balance=450.0, equity=431.01)

    assert snapshot["broker_running_pl"] == -18.99
    assert snapshot["broker_position_count"] == 2
    assert snapshot["attributed_position_count"] == 1
    assert snapshot["unattributed_position_count"] == 1
    assert snapshot["unattributed_symbols"] == ["NVDA"]
