"""Regression guard for capacity-rejected RL counterfactuals."""

from __future__ import annotations

from gungnir.config import Config, Secrets
from gungnir.data.models import Side, Signal
from gungnir.risk.portfolio import PortfolioRisk


def _risk(**raw) -> PortfolioRisk:
    risk = PortfolioRisk(Config({"risk": raw}, Secrets.from_env()))
    risk.equity = 10_000.0
    risk.day_start_equity = 10_000.0
    return risk


def test_capacity_rejection_can_build_isolated_counterfactual_order():
    """Learning may observe a capacity-vetoed idea without reopening capacity."""
    risk = _risk(max_open_positions=1)
    risk.open_exposure = {"AAA": 100.0}
    signal = Signal(strategy="mean_revert", symbol="US100", side=Side.BUY, conviction=0.8)

    assert risk.vet(signal, raw_volume=1.0, price=100.0, atr=2.0) is None
    assert risk.last_rejection["rule"] == "max_open_positions"

    order = risk.counterfactual_order(signal, raw_volume=1.0, price=100.0, atr=2.0)

    assert order is not None
    assert order.volume == 1.0
    assert order.stop_loss == 96.0
    assert order.take_profit == 106.0
    assert order.client_id.startswith("mean_revert:US100:")
    # The capacity veto remains recorded; counterfactual construction must not
    # mutate portfolio exposure or turn the rejected signal into an executable order.
    assert risk.open_exposure == {"AAA": 100.0}
    assert risk.last_rejection["rule"] == "max_open_positions"


import pytest

from gungnir.core.agent import Agent
from gungnir.execution.broker import PaperBroker
from gungnir.features.feature_store import FeatureSet
from gungnir.learning.rl import RLPolicy


@pytest.mark.asyncio
async def test_capacity_counterfactual_stays_learning_only_and_carries_reason():
    risk = _risk(max_open_positions=1)
    risk.open_exposure = {"AAA": 100.0}
    signal = Signal(strategy="mean_revert", symbol="US100", side=Side.BUY, conviction=0.8)
    features = FeatureSet(symbol="US100", last_price=100.0, atr=2.0)
    assert risk.vet(signal, raw_volume=1.0, price=100.0, atr=2.0) is None

    agent = object.__new__(Agent)
    agent.risk = risk
    agent.rl = RLPolicy(warmup_trades=0, seed=7)
    agent._rl_shadow_skipped = True
    agent.learn_broker = PaperBroker()
    agent.learn_broker.mark("US100", 100.0)
    agent._portfolio_heat = lambda: 0.0

    await agent._open_risk_counterfactual(
        signal, 1.0, features, book="real", regime=None,
        rejection=dict(risk.last_rejection or {}),
    )

    trade = agent.learn_broker.position("US100", "mean_revert")
    assert trade is not None
    assert trade.mode == "learning"
    assert trade.context["learning_only"] is True
    assert trade.context["counterfactual_risk_rejected"] is True
    assert trade.context["counterfactual_reason"] == "max_open_positions"
    assert trade.context["rl_action"] in (0, 1)
    assert risk.open_exposure == {"AAA": 100.0}
