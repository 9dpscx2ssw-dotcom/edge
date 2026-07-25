"""cci200_ema_pivot_app: faithful replica of the source "Scalping strategy
with CCI" app strategy.

Guards the 25 Jul addition of this strategy as a SEPARATE variant from
`cci200_ema_pivot`, which deliberately diverges from the app spec in three
ways: it requires a full EMA10>EMA21>EMA50 stack (app only requires EMA10
above both), it adds a price-vs-pivot ENTRY filter the app never specifies
(falsified by the app's own example chart, which shows a valid buy entered
*below* the daily pivot), and its `pivot` field is a per-bar artifact, not a
real daily pivot. This variant restores the literal rule plus the app's
pivot-target / EMA-cross exit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import (
    CCI200EMAPivotAppStrategy,
    _daily_pivot,
    _fx_point_size,
)


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, ema10=101.0, ema21=100.0,
                ema50=99.0, cci200=50.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> CCI200EMAPivotAppStrategy:
    return CCI200EMAPivotAppStrategy(params=params, mode="shadow", timeframe="15m")


def _daily_candle(high, low, close) -> Candle:
    return Candle(symbol="EURUSD", timeframe="1d", open=close, high=high, low=low,
                  close=close, ts=datetime(2026, 1, 1, tzinfo=timezone.utc))


# ── Entry: literal app rule, no full-stack requirement, no pivot filter ───────

def test_buy_only_requires_ema10_above_ema21_and_ema50_not_full_stack():
    # ema21 (100) is BELOW ema50 (105) — the tightened original would block
    # this (no ema10>ema21>ema50 chain); the app's literal rule doesn't care.
    s = _strat()
    sigs = s.generate(_feat(ema10=110.0, ema21=100.0, ema50=105.0, cci200=50.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_only_requires_ema10_below_ema21_and_ema50_not_full_stack():
    s = _strat()
    sigs = s.generate(_feat(ema10=90.0, ema21=100.0, ema50=95.0, cci200=-50.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_buy_fires_regardless_of_price_vs_pivot():
    # The app's own example chart shows a valid buy entered BELOW the daily
    # pivot — this strategy must not add a price-vs-pivot entry gate.
    s = _strat()
    sigs = s.generate(_feat(last_price=50.0, ema10=101.0, ema21=100.0,
                            ema50=99.0, cci200=50.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_cci_sign_still_required():
    s = _strat()
    assert s.generate(_feat(ema10=101.0, ema21=100.0, ema50=99.0, cci200=-1.0)) == []


def test_ema10_not_above_both_blocks_entry():
    s = _strat()
    assert s.generate(_feat(ema10=99.5, ema21=100.0, ema50=99.0, cci200=50.0)) == []


# ── Helpers: point size + daily pivot ──────────────────────────────────────────

def test_fx_point_size_jpy_vs_non_jpy():
    assert _fx_point_size("USDJPY") == 0.01
    assert _fx_point_size("EURUSD") == 0.0001
    assert _fx_point_size("US100") is None    # not a 6-letter currency pair
    assert _fx_point_size("BTCUSD") is None    # crypto handled elsewhere too, but 6 letters+digits-free — still not FX


def test_daily_pivot_from_last_completed_candle():
    p, r1, s1 = _daily_pivot([_daily_candle(high=110.0, low=90.0, close=100.0)])
    assert p == 100.0
    assert r1 == 110.0   # 2*100 - 90
    assert s1 == 90.0    # 2*100 - 110


def test_daily_pivot_empty_candles_returns_none():
    assert _daily_pivot([]) is None
    assert _daily_pivot(None) is None


# ── custom_brackets: fixed-points SL ───────────────────────────────────────────

def test_fixed_stop_points_sets_buy_stop_below_entry():
    s = _strat()
    result = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert result is not None
    stop, _ = result
    # 15 points * 0.0001 = 0.0015
    assert stop == 1.1000 - 0.0015


def test_fixed_stop_points_sets_sell_stop_above_entry():
    s = _strat()
    stop, _ = s.custom_brackets(Side.SELL, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 + 0.0015


def test_fixed_stop_points_uses_jpy_pip_size():
    s = _strat()
    stop, _ = s.custom_brackets(Side.BUY, entry_price=150.00, symbol="USDJPY")
    assert stop == 150.00 - 15 * 0.01


def test_fixed_stop_points_disabled_for_non_fx_symbol():
    # US100 isn't a recognized FX pair -> no point-size lookup -> stop stays None
    # (generic ATR bracket applies instead).
    s = _strat()
    result = s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100")
    # pivot target also None (no confirm features attached in this test) -> None overall
    assert result is None


def test_fixed_stop_points_toggle_off():
    s = _strat(fixed_stop_points=0.0)
    result = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert result is None


# ── custom_brackets: pivot-target TP ───────────────────────────────────────────

def test_pivot_target_buy_below_pivot_targets_pivot():
    s = _strat()
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=110.0, low=90.0, close=100.0)]
    _, tp = s.custom_brackets(Side.BUY, entry_price=95.0, symbol="US100")
    assert tp == 100.0   # pivot itself, since entry is below it


def test_pivot_target_buy_above_pivot_targets_r1():
    s = _strat()
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=110.0, low=90.0, close=100.0)]
    _, tp = s.custom_brackets(Side.BUY, entry_price=105.0, symbol="US100")
    assert tp == 110.0   # R1, since entry is already above pivot


def test_pivot_target_sell_above_pivot_targets_pivot():
    s = _strat()
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=110.0, low=90.0, close=100.0)]
    _, tp = s.custom_brackets(Side.SELL, entry_price=105.0, symbol="US100")
    assert tp == 100.0


def test_pivot_target_sell_below_pivot_targets_s1():
    s = _strat()
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=110.0, low=90.0, close=100.0)]
    _, tp = s.custom_brackets(Side.SELL, entry_price=95.0, symbol="US100")
    assert tp == 90.0


def test_pivot_target_toggle_off():
    s = _strat(pivot_target_exit_enabled=0.0)
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=110.0, low=90.0, close=100.0)]
    result = s.custom_brackets(Side.BUY, entry_price=95.0, symbol="US100")
    assert result is None


def test_pivot_target_no_confirm_features_yields_no_tp():
    s = _strat()
    assert s._confirm_features is None
    result = s.custom_brackets(Side.BUY, entry_price=95.0, symbol="US100")
    assert result is None


def test_both_legs_combine_for_fx_symbol():
    s = _strat()
    s._confirm_features = _feat()
    s._confirm_features.candles = [_daily_candle(high=1.1100, low=1.0900, close=1.1000)]
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.0950, symbol="EURUSD")
    assert stop == 1.0950 - 0.0015
    assert tp == 1.1000   # below pivot -> targets pivot


# ── ema_cross_exit toggle ──────────────────────────────────────────────────────

def test_ema_cross_exit_defaults_on():
    s = _strat()
    assert s.ema_cross_exit is True


def test_ema_cross_exit_can_be_disabled():
    s = _strat(ema_cross_exit_enabled=0.0)
    assert s.ema_cross_exit is False


def test_confirm_timeframe_declared():
    s = _strat()
    assert s.confirm_timeframe == "1d"
