"""alligator: overwritten in place to match the source "Alligator" app
strategy — never faithful to begin with (generic ATR bracket instead of the
app's SMA144-tracking stop and lips/teeth reversal close), so nothing prior
to protect.

Entry (SMA144 filter + full lips>teeth>jaw alignment) was already faithful
and is unchanged. This guards the two new generic exit hooks introduced for
it: `trail_field` (an arbitrary-FeatureSet-field trailing stop, generalizing
the EMA-only `trail_ema_period`) and `alligator_cross_exit`.
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.execution.fx import point_size
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import AlligatorStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0,
                alligator_lips=103.0, alligator_teeth=102.0, alligator_jaw=101.0,
                sma144=95.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> AlligatorStrategy:
    return AlligatorStrategy(params=params, mode="shadow", timeframe="1h")


# ── Entry (unchanged) ───────────────────────────────────────────────────────

def test_buy_requires_full_alignment_above_sma144():
    s = _strat()
    sigs = s.generate(_feat(last_price=100.0, sma144=95.0,
                            alligator_lips=103.0, alligator_teeth=102.0, alligator_jaw=101.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_requires_full_alignment_below_sma144():
    s = _strat()
    sigs = s.generate(_feat(last_price=90.0, sma144=95.0,
                            alligator_lips=97.0, alligator_teeth=98.0, alligator_jaw=99.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_alignment_without_sma144_filter_does_not_fire():
    s = _strat()
    assert s.generate(_feat(last_price=90.0, sma144=95.0,
                            alligator_lips=103.0, alligator_teeth=102.0, alligator_jaw=101.0)) == []


def test_partial_alignment_does_not_fire():
    s = _strat()
    # teeth not below jaw -> not a full stack.
    assert s.generate(_feat(last_price=100.0, sma144=95.0,
                            alligator_lips=103.0, alligator_teeth=101.0, alligator_jaw=102.0)) == []


# ── Generic field-trailing hook declaration ────────────────────────────────────

def test_declares_sma144_as_the_trail_field():
    s = _strat()
    assert s.trail_field == "sma144"
    assert s.p("trail_buffer_points") == 1.0


def test_trail_field_toggle():
    on = _strat()
    off = _strat(trail_field_enabled=0.0)
    assert on.p("trail_field_enabled") > 0
    assert off.p("trail_field_enabled") == 0.0


# ── alligator_cross_exit toggle ─────────────────────────────────────────────────

def test_alligator_cross_exit_defaults_on():
    s = _strat()
    assert s.alligator_cross_exit is True


def test_alligator_cross_exit_can_be_disabled():
    s = _strat(alligator_cross_exit_enabled=0.0)
    assert s.alligator_cross_exit is False


# ── shared fx.point_size (moved from a kraken_strategies-local helper) ────────

def test_point_size_used_for_the_trail_buffer():
    assert point_size("EURUSD") == 0.0001
    assert point_size("USDJPY") == 0.01
    assert point_size("US100") is None
