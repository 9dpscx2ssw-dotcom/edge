"""goldmine_xauusd: faithful replica of the source "Goldmine" app strategy
(BB(20,2) + Stochastic(5,3,3), for XAUUSD/GOLD, D1).
"""

from __future__ import annotations

from datetime import datetime, timezone

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import GoldmineXAUUSDStrategy


def _candle(open_, close) -> Candle:
    return Candle(symbol="GOLD", timeframe="1d", open=open_, high=max(open_, close) + 1,
                  low=min(open_, close) - 1, close=close, ts=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _feat(**over):
    base = dict(symbol="GOLD", last_price=110.0, bb_lower=95.0, bb_mid=100.0, bb_upper=110.0,
                stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0,
                candles=[_candle(112.0, 110.0)], atr=1.0)   # bearish candle by default
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> GoldmineXAUUSDStrategy:
    return GoldmineXAUUSDStrategy(params=params, mode="shadow", timeframe="1d")


# ── Entry: band touch + candle color + stochastic zone/slope ──────────────────

def test_sell_fires_at_upper_band_bearish_candle_overbought_falling_stoch():
    s = _strat()
    sigs = s.generate(_feat(last_price=110.0, bb_upper=110.0,
                            candles=[_candle(112.0, 110.0)],
                            stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_buy_fires_at_lower_band_bullish_candle_oversold_rising_stoch():
    s = _strat()
    sigs = s.generate(_feat(last_price=95.0, bb_lower=95.0,
                            candles=[_candle(93.0, 95.0)],
                            stoch5_k=15.0, stoch5_d=15.0, prev_stoch5_k=10.0, prev_stoch5_d=10.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_blocked_if_candle_is_bullish():
    s = _strat()
    sigs = s.generate(_feat(last_price=110.0, bb_upper=110.0,
                            candles=[_candle(108.0, 110.0)],   # bullish, not bearish
                            stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    assert sigs == []


def test_sell_blocked_if_stochastic_not_overbought():
    s = _strat()
    sigs = s.generate(_feat(last_price=110.0, bb_upper=110.0,
                            candles=[_candle(112.0, 110.0)],
                            stoch5_k=50.0, stoch5_d=50.0, prev_stoch5_k=55.0, prev_stoch5_d=55.0))
    assert sigs == []


def test_sell_blocked_if_stochastic_rising_not_falling():
    s = _strat()
    sigs = s.generate(_feat(last_price=110.0, bb_upper=110.0,
                            candles=[_candle(112.0, 110.0)],
                            stoch5_k=90.0, stoch5_d=90.0, prev_stoch5_k=85.0, prev_stoch5_d=85.0))
    assert sigs == []


def test_price_not_at_band_blocks_entry():
    s = _strat()
    sigs = s.generate(_feat(last_price=100.0, bb_upper=110.0, bb_lower=95.0,
                            candles=[_candle(101.0, 100.0)],
                            stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    assert sigs == []


def test_slope_confirm_toggle_off():
    s = _strat(stoch_slope_confirm_enabled=0.0)
    sigs = s.generate(_feat(last_price=110.0, bb_upper=110.0,
                            candles=[_candle(112.0, 110.0)],
                            stoch5_k=90.0, stoch5_d=90.0, prev_stoch5_k=85.0, prev_stoch5_d=85.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_no_candles_never_fires():
    s = _strat()
    assert s.generate(_feat(candles=[])) == []


# ── custom_brackets: TP at entry-time BB mid, SL = TP-distance / 3 ────────────

def test_sell_brackets_target_entry_time_bb_mid():
    s = _strat()
    s.generate(_feat(last_price=110.0, bb_upper=110.0, bb_mid=100.0,
                     candles=[_candle(112.0, 110.0)],
                     stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    stop, tp = s.custom_brackets(Side.SELL, entry_price=110.0, symbol="GOLD")
    assert tp == 100.0
    assert stop == 110.0 + (10.0 / 3.0)


def test_buy_brackets_target_entry_time_bb_mid():
    s = _strat()
    s.generate(_feat(last_price=95.0, bb_lower=95.0, bb_mid=100.0,
                     candles=[_candle(93.0, 95.0)],
                     stoch5_k=15.0, stoch5_d=15.0, prev_stoch5_k=10.0, prev_stoch5_d=10.0))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=95.0, symbol="GOLD")
    assert tp == 100.0
    assert stop == 95.0 - (5.0 / 3.0)


def test_no_prior_entry_yields_none():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=95.0, symbol="GOLD") is None


def test_fixed_exit_toggle_off():
    s = _strat(fixed_exit_enabled=0.0)
    s.generate(_feat(last_price=110.0, bb_upper=110.0, bb_mid=100.0,
                     candles=[_candle(112.0, 110.0)],
                     stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    assert s.custom_brackets(Side.SELL, entry_price=110.0, symbol="GOLD") is None


def test_works_for_non_fx_instrument_no_point_size_needed():
    # Unlike the FX-point-based strategies, this is pure price distance —
    # must work for GOLD, which isn't a 6-letter currency pair.
    s = _strat()
    s.generate(_feat(last_price=110.0, bb_upper=110.0, bb_mid=100.0,
                     candles=[_candle(112.0, 110.0)],
                     stoch5_k=85.0, stoch5_d=85.0, prev_stoch5_k=90.0, prev_stoch5_d=90.0))
    result = s.custom_brackets(Side.SELL, entry_price=110.0, symbol="GOLD")
    assert result is not None
