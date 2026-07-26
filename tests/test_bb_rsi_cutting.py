"""bb_rsi_cutting: overwritten in place to match the source "Cutting Points"
app strategy — never faithful to begin with (mode: off, no prior track
record), so nothing prior to protect.

Covers the two-phase entry (band+RSI(7)+ADX arms the setup; price returning
inside the band triggers it) and the exit brackets (BB-mid TP by default, a
toggleable "quick" fixed-points TP, and a band-anchored SL).
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import BBRSICuttingStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, bb_lower=98.0, bb_mid=100.0,
                bb_upper=102.0, rsi7=50.0, adx=15.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> BBRSICuttingStrategy:
    return BBRSICuttingStrategy(params=params, mode="shadow", timeframe="5m")


# ── Entry: two-phase arm-then-trigger, using RSI(7) not the shared RSI(14) ────

def test_arm_alone_does_not_fire():
    s = _strat()
    assert s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, adx=15.0)) == []


def test_buy_fires_when_price_returns_above_lower_band_after_arming():
    s = _strat()
    s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, adx=15.0))   # arm
    sigs = s.generate(_feat(last_price=98.5, bb_lower=98.0, rsi7=28.0, adx=16.0))  # trigger
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_fires_when_price_returns_below_upper_band_after_arming():
    s = _strat()
    s.generate(_feat(last_price=103.0, bb_upper=102.0, rsi7=75.0, adx=15.0))
    sigs = s.generate(_feat(last_price=101.5, bb_upper=102.0, rsi7=72.0, adx=16.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_high_adx_blocks_arming():
    s = _strat()
    s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, adx=45.0))   # ADX too high, no arm
    sigs = s.generate(_feat(last_price=98.5, bb_lower=98.0, rsi7=28.0, adx=16.0))
    assert sigs == []   # never armed -> no trigger


def test_state_persists_across_bars_while_still_below_band():
    s = _strat()
    s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, adx=15.0))   # arm
    s.generate(_feat(last_price=96.5, bb_lower=98.0, rsi7=32.0, adx=15.0))   # RSI drifted out of zone, still below band
    sigs = s.generate(_feat(last_price=98.2, bb_lower=98.0, rsi7=32.0, adx=15.0))  # returns above
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_consumed_arm_does_not_refire():
    s = _strat()
    s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, adx=15.0))
    s.generate(_feat(last_price=98.5, bb_lower=98.0, rsi7=28.0, adx=16.0))   # fires, consumes
    sigs = s.generate(_feat(last_price=98.6, bb_lower=98.0, rsi7=28.0, adx=16.0))
    assert sigs == []


def test_uses_rsi7_not_the_shared_rsi14():
    s = _strat()
    # rsi (shared 14) disagrees with rsi7 -> must follow rsi7.
    s.generate(_feat(last_price=97.0, bb_lower=98.0, rsi7=25.0, rsi=60.0, adx=15.0))
    assert s._pending["EURUSD"] == "buy"


# ── custom_brackets: BB-mid TP (default) or quick fixed-points TP, band SL ────

def test_default_tp_is_bb_mid_sl_is_band_plus_buffer():
    s = _strat()
    s.generate(_feat(last_price=97.0, bb_lower=98.0, bb_mid=100.0, rsi7=25.0, adx=15.0))
    s.generate(_feat(last_price=98.5, bb_lower=98.0, bb_mid=100.0, rsi7=28.0, adx=16.0))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=98.5, symbol="EURUSD")
    assert tp == 100.0
    assert stop == 98.0 - 3.0 * 0.0001


def test_quick_tp_toggle_uses_fixed_points_instead_of_bb_mid():
    s = _strat(quick_tp_enabled=1.0, quick_tp_points=4.0)
    s.generate(_feat(last_price=97.0, bb_lower=98.0, bb_mid=100.0, rsi7=25.0, adx=15.0))
    s.generate(_feat(last_price=98.5, bb_lower=98.0, bb_mid=100.0, rsi7=28.0, adx=16.0))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=98.5, symbol="EURUSD")
    assert tp == 98.5 + 4.0 * 0.0001


def test_sell_brackets_invert_direction():
    s = _strat()
    s.generate(_feat(last_price=103.0, bb_upper=102.0, bb_mid=100.0, rsi7=75.0, adx=15.0))
    s.generate(_feat(last_price=101.5, bb_upper=102.0, bb_mid=100.0, rsi7=72.0, adx=16.0))
    stop, tp = s.custom_brackets(Side.SELL, entry_price=101.5, symbol="EURUSD")
    assert tp == 100.0
    assert stop == 102.0 + 3.0 * 0.0001


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _strat(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=98.5, symbol="EURUSD") is None
