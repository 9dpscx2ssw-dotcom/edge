"""ema_stoch_rsi: overwritten in place to match the source "EMA + Stochastic
+ RSI" app spec (never split into a separate variant, since the prior
version wasn't faithful in the first place — see the class docstring).

Covers the three restored legs: stochastic %K/%D slope confirmation on
entry, the stochastic-exhaustion exit (70/30, distinct from the entry-side
80/20 zone bounds), and the previous-swing-low/high stop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import EMAStochRSIStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, ema5=101.0, ema10=100.0,
                rsi=55.0, stoch_k=50.0, stoch_d=50.0, prev_stoch_k=45.0,
                prev_stoch_d=45.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> EMAStochRSIStrategy:
    return EMAStochRSIStrategy(params=params, mode="shadow", timeframe="1h")


def _candles(lows_highs: list[tuple[float, float]]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol="EURUSD", timeframe="1h", open=(lo + hi) / 2, high=hi,
                   low=lo, close=(lo + hi) / 2, ts=start + timedelta(hours=i))
            for i, (lo, hi) in enumerate(lows_highs)]


# ── Entry: stochastic slope confirmation ───────────────────────────────────────

def test_buy_requires_both_stoch_lines_rising():
    s = _strat()
    sigs = s.generate(_feat(stoch_k=55.0, prev_stoch_k=50.0,
                            stoch_d=52.0, prev_stoch_d=48.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_buy_blocked_when_stoch_k_falling_even_if_level_ok():
    s = _strat()
    # Level condition (stoch_k=50 < 80) holds, but %K is falling, not rising.
    sigs = s.generate(_feat(stoch_k=45.0, prev_stoch_k=50.0,
                            stoch_d=52.0, prev_stoch_d=48.0))
    assert sigs == []


def test_buy_blocked_when_stoch_d_not_rising():
    s = _strat()
    sigs = s.generate(_feat(stoch_k=55.0, prev_stoch_k=50.0,
                            stoch_d=45.0, prev_stoch_d=48.0))
    assert sigs == []


def test_sell_requires_both_stoch_lines_falling():
    s = _strat()
    sigs = s.generate(_feat(ema5=90.0, ema10=100.0, rsi=45.0,
                            stoch_k=45.0, prev_stoch_k=50.0,
                            stoch_d=42.0, prev_stoch_d=48.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_slope_confirm_toggle_off_reverts_to_level_only():
    s = _strat(stoch_slope_confirm_enabled=0.0)
    sigs = s.generate(_feat(stoch_k=45.0, prev_stoch_k=50.0,  # falling
                            stoch_d=52.0, prev_stoch_d=48.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


# ── Entry: zone-boundary + RSI legs still enforced ─────────────────────────────

def test_buy_still_blocked_in_overbought_zone():
    s = _strat()
    sigs = s.generate(_feat(stoch_k=85.0, prev_stoch_k=80.0,
                            stoch_d=82.0, prev_stoch_d=78.0))
    assert sigs == []


def test_buy_still_requires_rsi_above_mid():
    s = _strat()
    sigs = s.generate(_feat(rsi=45.0, stoch_k=55.0, prev_stoch_k=50.0,
                            stoch_d=52.0, prev_stoch_d=48.0))
    assert sigs == []


# ── custom_brackets: previous swing low/high stop ──────────────────────────────

def test_buy_stop_at_swing_low_of_lookback_window():
    s = _strat(swing_lookback=3.0)
    s._entry_candles = _candles([(95.0, 105.0), (90.0, 104.0), (96.0, 106.0)])
    result = s.custom_brackets(Side.BUY, entry_price=106.0, symbol="EURUSD")
    assert result == (90.0, None)


def test_sell_stop_at_swing_high_of_lookback_window():
    s = _strat(swing_lookback=3.0)
    s._entry_candles = _candles([(95.0, 105.0), (90.0, 108.0), (96.0, 106.0)])
    result = s.custom_brackets(Side.SELL, entry_price=90.0, symbol="EURUSD")
    assert result == (108.0, None)


def test_swing_stop_only_uses_the_last_lookback_bars():
    s = _strat(swing_lookback=2.0)
    # Lowest low (80.0) is outside the 2-bar lookback window — excluded.
    s._entry_candles = _candles([(80.0, 90.0), (95.0, 105.0), (96.0, 106.0)])
    result = s.custom_brackets(Side.BUY, entry_price=106.0, symbol="EURUSD")
    assert result == (95.0, None)


def test_swing_stop_rejected_if_on_wrong_side_of_entry():
    s = _strat(swing_lookback=3.0)
    # Swing low (99.0) is above the entry price — nonsensical as a long stop.
    s._entry_candles = _candles([(99.0, 105.0), (100.0, 104.0), (101.0, 106.0)])
    assert s.custom_brackets(Side.BUY, entry_price=98.0, symbol="EURUSD") is None


def test_swing_stop_toggle_off():
    s = _strat(swing_stop_enabled=0.0)
    s._entry_candles = _candles([(90.0, 105.0)])
    assert s.custom_brackets(Side.BUY, entry_price=106.0, symbol="EURUSD") is None


def test_swing_stop_no_entry_candles_yields_none():
    s = _strat()
    assert s._entry_candles == []
    assert s.custom_brackets(Side.BUY, entry_price=100.0, symbol="EURUSD") is None


# ── stoch_exhaustion_exit toggle ────────────────────────────────────────────────

def test_stoch_exhaustion_exit_defaults_on():
    s = _strat()
    assert s.stoch_exhaustion_exit is True


def test_stoch_exhaustion_exit_can_be_disabled():
    s = _strat(stoch_exhaustion_exit_enabled=0.0)
    assert s.stoch_exhaustion_exit is False
