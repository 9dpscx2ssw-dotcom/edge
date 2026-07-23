from __future__ import annotations

import pytest

from gungnir.core.aggregator import SignalAggregator
from gungnir.data.models import Side


def test_consensus_diagnostics_include_each_effective_vote_and_reconcile_total():
    agg = SignalAggregator(ema_alpha=1.0, family_cap=0.4)
    agg.set_stance("US100", "fast", Side.BUY, 1.0, family="trend", horizon="M5")
    agg.set_stance("US100", "slow", Side.SELL, 1.0, family="meanrev", horizon="H1")
    decision = agg.decide("US100", None)

    votes = decision.diagnostics["votes"]
    assert {vote["strategy_id"] for vote in votes} == {"fast", "slow"}
    assert all({"side", "raw_weight", "horizon_weight", "family", "effective_weight"} <= vote.keys() for vote in votes)
    assert sum(vote["effective_weight"] for vote in votes) == pytest.approx(
        decision.diagnostics["effective_total"]
    )



def test_consensus_effective_total_uses_vote_snapshot_precision():
    agg = SignalAggregator(ema_alpha=1.0, family_cap=1.0)
    agg.set_stance("US100", "one", Side.BUY, 0.123456789, family="trend", horizon="M5")
    agg.set_stance("US100", "two", Side.SELL, 0.234567891, family="meanrev", horizon="M5")
    decision = agg.decide("US100", None)
    assert decision.diagnostics["effective_total"] == sum(
        vote["effective_weight"] for vote in decision.diagnostics["votes"]
    )
