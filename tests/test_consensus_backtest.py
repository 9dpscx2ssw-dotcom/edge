"""Consensus backtesting must replay the real SignalAggregator over a candle series."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gungnir.backtest import engine
from gungnir.core.aggregator import SignalAggregator
from gungnir.data.models import Candle, Side, Signal
from gungnir.strategy.base import Strategy


class _Always(Strategy):
    family = "test"

    def __init__(self, name: str, side: Side, conviction: float = 1.0):
        super().__init__(mode="shadow", symbols=["US500"], timeframe="1h")
        self.name = name
        self.side = side
        self.conviction = conviction

    def generate(self, features):
        return [Signal(strategy=self.name, symbol="US500", side=self.side, conviction=self.conviction)]


def _candles(n: int = 90):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(symbol="US500", timeframe="1h", open=100 + i, high=101 + i,
               low=99 + i, close=100.5 + i, volume=1000,
               ts=base + timedelta(hours=i))
        for i in range(n)
    ]


def _agg():
    return SignalAggregator(ema_alpha=1.0, enter_threshold=0.25,
                            exit_threshold=0.10, min_hold_bars=0,
                            family_cap=0.0, veto_opposing=0.35)


def test_consensus_backtest_enters_one_aggregate_trade_not_one_per_strategy():
    candles = _candles()
    result = engine.run_consensus(
        [_Always("a", Side.BUY), _Always("b", Side.BUY)], candles, "US500",
        aggregator=_agg(), warmup=20, sl_pct=99.0, tp_pct=99_999.0,
    )
    assert result.metrics.n_trades == 1
    assert [trade.strategy for trade in result.trades] == ["consensus"]
    assert result.trades[0].side == Side.BUY
    assert result.consensus_actions["enter"] == 1


def test_consensus_backtest_respects_conflict_veto():
    result = engine.run_consensus(
        [_Always("buy", Side.BUY, 1.0), _Always("sell", Side.SELL, 0.6)], _candles(), "US500",
        aggregator=_agg(), warmup=20,
    )
    assert result.metrics.n_trades == 0
    assert result.consensus_actions["veto"] > 0
