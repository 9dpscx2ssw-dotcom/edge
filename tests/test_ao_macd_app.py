"""ao_macd_app: faithful replica of the source "Awesome and MACD" app
strategy — a momentum-pullback entry (AO zero-cross confirmed by the MACD
histogram's still-opposite zone), kept separate from `ao_macd`, which uses a
static same-direction level check instead.
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import AwesomeMACDAppStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, ao=0.0, prev_ao=0.0,
                macd_hist_5_7=0.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> AwesomeMACDAppStrategy:
    return AwesomeMACDAppStrategy(params=params, mode="shadow", timeframe="4h")


# ── Entry: AO zero-cross confirmed by the opposite-zone MACD histogram ────────

def test_buy_fires_on_ao_cross_down_through_zero_with_positive_histogram():
    s = _strat()
    sigs = s.generate(_feat(prev_ao=0.002, ao=-0.001, macd_hist_5_7=0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_fires_on_ao_cross_up_through_zero_with_negative_histogram():
    s = _strat()
    sigs = s.generate(_feat(prev_ao=-0.002, ao=0.001, macd_hist_5_7=-0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_no_ao_cross_never_fires():
    s = _strat()
    assert s.generate(_feat(prev_ao=0.002, ao=0.001, macd_hist_5_7=0.001)) == []


def test_ao_cross_down_with_histogram_already_negative_does_not_fire():
    # Histogram must still be in the OPPOSITE (positive) zone for a buy —
    # if it's already flipped negative too, this isn't the app's setup.
    s = _strat()
    assert s.generate(_feat(prev_ao=0.002, ao=-0.001, macd_hist_5_7=-0.001)) == []


def test_ao_cross_up_with_histogram_already_positive_does_not_fire():
    s = _strat()
    assert s.generate(_feat(prev_ao=-0.002, ao=0.001, macd_hist_5_7=0.001)) == []


# ── custom_brackets: fixed points TP/SL ────────────────────────────────────────

def test_buy_brackets_use_default_60pt_tp_and_20pt_sl():
    s = _strat()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 - 20.0 * 0.0001
    assert tp == 1.1000 + 60.0 * 0.0001


def test_sell_brackets_invert_direction():
    s = _strat()
    stop, tp = s.custom_brackets(Side.SELL, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 + 20.0 * 0.0001
    assert tp == 1.1000 - 60.0 * 0.0001


def test_tp_points_tunable_within_app_range():
    s = _strat(tp_points=70.0)
    _, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert tp == 1.1000 + 70.0 * 0.0001


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _strat(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD") is None
