"""Regression tests for the two independent EMA strategy families."""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from pathlib import Path

from gungnir.strategy.kraken_strategies import (
    EMA921ADXDMITrendM5Strategy,
    EMA921EMA78TrendM5Strategy,
)
from gungnir.strategy.registry import StrategyRegistry


def _features(**overrides) -> KrakenFeatureSet:
    values = {
        "symbol": "US100",
        "last_price": 101.0,
        "atr": 1.0,
        "ema7": 101.0,
        "prev_ema7": 100.0,
        "ema8": 100.0,
        "prev_ema8": 99.0,
        "ema9": 101.0,
        "prev_ema9": 99.0,
        "ema21": 100.0,
        "prev_ema21": 100.0,
        "ema55": 99.0,
        "adx": 30.0,
        "plus_di": 25.0,
        "minus_di": 15.0,
        "momentum_zero": 1.0,
        "dmi_histogram": 10.0,
    }
    values.update(overrides)
    return KrakenFeatureSet.model_construct(**values)


def test_adx_dmi_strategy_emits_long_only_for_confirmed_bull_cross():
    result = EMA921ADXDMITrendM5Strategy().generate(_features())
    assert len(result) == 1
    assert result[0].side is Side.BUY
    assert "EMA9↑EMA21" in result[0].rationale


def test_adx_dmi_strategy_emits_short_for_complete_opposite_setup():
    f = _features(
        last_price=98.0,
        ema9=99.0, prev_ema9=101.0,
        ema21=100.0, prev_ema21=100.0,
        ema55=100.0,
        momentum_zero=-1.0,
        plus_di=10.0, minus_di=25.0,
        dmi_histogram=-15.0,
    )
    result = EMA921ADXDMITrendM5Strategy().generate(f)
    assert len(result) == 1
    assert result[0].side is Side.SELL


def test_adx_dmi_strategy_rejects_level_without_a_new_cross():
    f = _features(prev_ema9=101.0, prev_ema21=100.0)
    assert EMA921ADXDMITrendM5Strategy().generate(f) == []


def test_ema78_strategy_buys_on_a_bullish_7_8_cross_without_any_ema921_or_filter_data():
    f = _features(
        ema7=101.0, prev_ema7=99.0,
        ema8=100.0, prev_ema8=100.0,
        ema9=float("nan"), prev_ema9=float("nan"),
        ema21=float("nan"), prev_ema21=float("nan"), ema55=float("nan"),
        momentum_zero=float("nan"), adx=float("nan"), dmi_histogram=float("nan"),
    )
    result = EMA921EMA78TrendM5Strategy().generate(f)
    assert len(result) == 1
    assert result[0].side is Side.BUY
    assert result[0].rationale == "EMA7↑EMA8; standalone bullish crossover"


def test_ema78_strategy_sells_on_a_bearish_7_8_cross_without_any_ema921_or_filter_data():
    f = _features(
        ema7=99.0, prev_ema7=101.0,
        ema8=100.0, prev_ema8=100.0,
        ema9=float("nan"), prev_ema9=float("nan"),
        ema21=float("nan"), prev_ema21=float("nan"), ema55=float("nan"),
        momentum_zero=float("nan"), adx=float("nan"), dmi_histogram=float("nan"),
    )
    result = EMA921EMA78TrendM5Strategy().generate(f)
    assert len(result) == 1
    assert result[0].side is Side.SELL
    assert result[0].rationale == "EMA7↓EMA8; standalone bearish crossover"


def test_ema78_strategy_requires_a_new_cross():
    f = _features(ema7=101.0, prev_ema7=101.0, ema8=100.0, prev_ema8=100.0)
    assert EMA921EMA78TrendM5Strategy().generate(f) == []


def test_oracle_config_registers_four_independently_attributed_ema_instances():
    registry = StrategyRegistry.from_yaml(Path(__file__).resolve().parents[1] / "config/strategies.yaml")
    found = {s.name: s.timeframe for s in registry.all() if s.name.startswith(("ema921_", "ema78_"))}
    assert found == {
        "ema921_adx_dmi_m5": "5m",
        "ema921_adx_dmi_m15": "15m",
        "ema78_crossover_m5": "5m",
        "ema78_crossover_m15": "15m",
    }
