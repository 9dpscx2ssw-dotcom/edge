"""speculative_zigzag_rsi: faithful replica of the source "Speculative" app
strategy (ZigZag(Depth=100)-as-confirmed-fractal-swing + RSI(14)).

Covers the swing-confirmation entry (using a small order for test-sized
candle windows instead of the real depth=100), and the stop-loss-triggered
directional lockout ("wait for the opposite signal").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import SpeculativeZigzagRSIStrategy


def _candles(lows_highs: list[tuple[float, float]]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol="EURUSD", timeframe="15m", open=(lo + hi) / 2, high=hi,
                   low=lo, close=(lo + hi) / 2, ts=start + timedelta(minutes=15 * i))
            for i, (lo, hi) in enumerate(lows_highs)]


# order=2 -> window=5 candles, middle bar (index 2) is the pivot candidate.
_PEAK = _candles([(80.0, 90.0), (90.0, 100.0), (105.0, 115.0), (91.0, 101.0), (85.0, 95.0)])
_DIP = _candles([(100.0, 110.0), (95.0, 108.0), (85.0, 105.0), (96.0, 109.0), (99.0, 111.0)])
_FLAT = _candles([(90.0 + i, 100.0 + i) for i in range(5)])   # monotonic -> no confirmed pivot


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, rsi=50.0, candles=_PEAK, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> SpeculativeZigzagRSIStrategy:
    p = {"zigzag_depth": 2.0}
    p.update(params)
    return SpeculativeZigzagRSIStrategy(params=p, mode="shadow", timeframe="15m")


# ── Entry: confirmed swing pivot + RSI ─────────────────────────────────────────

def test_sell_fires_on_confirmed_swing_high_with_overbought_rsi():
    s = _strat()
    sigs = s.generate(_feat(candles=_PEAK, rsi=75.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_buy_fires_on_confirmed_swing_low_with_oversold_rsi():
    s = _strat()
    sigs = s.generate(_feat(candles=_DIP, rsi=25.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_no_confirmed_pivot_never_fires():
    s = _strat()
    assert s.generate(_feat(candles=_FLAT, rsi=75.0)) == []


def test_pivot_without_rsi_confirmation_does_not_fire():
    s = _strat()
    assert s.generate(_feat(candles=_PEAK, rsi=50.0)) == []


def test_not_enough_candles_never_fires():
    s = _strat()
    assert s.generate(_feat(candles=_PEAK[:3], rsi=75.0)) == []


# ── Stop-loss-triggered directional lockout ────────────────────────────────────

def test_stop_loss_blocks_same_direction_reentry():
    s = _strat()
    sigs1 = s.generate(_feat(candles=_DIP, rsi=25.0))
    assert len(sigs1) == 1 and sigs1[0].side == Side.BUY
    s.on_position_closed("EURUSD", Side.BUY, "stop-loss")
    # Same setup recurs -> must be suppressed now.
    sigs2 = s.generate(_feat(candles=_DIP, rsi=25.0))
    assert sigs2 == []


def test_opposite_signal_fires_and_clears_the_block():
    s = _strat()
    s.on_position_closed("EURUSD", Side.BUY, "stop-loss")
    # The blocked side (buy) stays blocked...
    assert s.generate(_feat(candles=_DIP, rsi=25.0)) == []
    # ...but a genuine sell signal fires and clears the block.
    sigs = s.generate(_feat(candles=_PEAK, rsi=75.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL
    sigs2 = s.generate(_feat(candles=_DIP, rsi=25.0))
    assert len(sigs2) == 1 and sigs2[0].side == Side.BUY


def test_breakeven_stop_also_triggers_the_lockout():
    s = _strat()
    s.on_position_closed("EURUSD", Side.SELL, "breakeven-stop")
    assert s.generate(_feat(candles=_PEAK, rsi=75.0)) == []


def test_take_profit_close_does_not_trigger_the_lockout():
    s = _strat()
    s.on_position_closed("EURUSD", Side.SELL, "take-profit")
    sigs = s.generate(_feat(candles=_PEAK, rsi=75.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_lockout_is_per_symbol():
    s = _strat()
    s.on_position_closed("EURUSD", Side.BUY, "stop-loss")
    assert s.generate(_feat(symbol="GBPUSD", candles=_DIP, rsi=25.0))


# ── custom_brackets: fixed points TP/SL ────────────────────────────────────────

def test_buy_brackets_use_default_points():
    s = _strat()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 - 17.5 * 0.0001
    assert tp == 1.1000 + 80.0 * 0.0001


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _strat(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD") is None
