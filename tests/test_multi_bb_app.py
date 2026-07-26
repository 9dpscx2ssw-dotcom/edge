"""multi_bb_app: faithful replica of the source "Bollinger Bands for
GBP/JPY" app strategy.

Kept separate from `multi_bb`, which collapsed the app's three-band (dev
2/3/4) system to a single dev=2 band with an unbounded entry. This variant
restores the bounded dev2-to-dev3 entry zone, the fixed-point exits
(2-point swing-buffer SL, 15-point TP), and scopes to GBP/JPY.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import (
    KrakenFeatureSet,
    build_kraken,
    build_kraken_series,
)
from gungnir.strategy.kraken_strategies import MultiBBAppStrategy


def _feat(**over):
    base = dict(symbol="GBPJPY", last_price=100.0,
                bb_lower=98.0, bb_mid=100.0, bb_upper=102.0,
                bb3_lower=96.0, bb3_upper=104.0,
                bb4_lower=94.0, bb4_upper=106.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> MultiBBAppStrategy:
    return MultiBBAppStrategy(params=params, mode="shadow", timeframe="15m")


def _candles(lows_highs: list[tuple[float, float]]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol="GBPJPY", timeframe="15m", open=(lo + hi) / 2, high=hi,
                   low=lo, close=(lo + hi) / 2, ts=start + timedelta(minutes=15 * i))
            for i, (lo, hi) in enumerate(lows_highs)]


# ── Entry: bounded dev2-to-dev3 zone, not an unbounded single-band trigger ────

def test_buy_fires_inside_the_dev2_dev3_zone():
    s = _strat()
    sigs = s.generate(_feat(last_price=97.0))   # between bb3_lower(96) and bb_lower(98)
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_buy_fires_exactly_at_dev2_line():
    s = _strat()
    sigs = s.generate(_feat(last_price=98.0))   # == bb_lower
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_price_inside_dev2_band_does_not_fire():
    s = _strat()
    assert s.generate(_feat(last_price=99.0)) == []   # inside bb_lower..bb_upper


def test_price_beyond_dev3_does_not_fire_even_though_it_passed_dev2():
    # multi_bb (the unbounded original) WOULD fire here; the app's bounded
    # zone (dev2-dev3) does not extend this far.
    s = _strat()
    assert s.generate(_feat(last_price=95.0)) == []   # below bb3_lower(96)


def test_price_beyond_dev4_still_does_not_fire():
    # dev4 isn't gated on directly, but the dev3 bound already excludes it —
    # confirms dev4 isn't accidentally re-widening the zone.
    s = _strat()
    assert s.generate(_feat(last_price=90.0)) == []   # well past bb4_lower(94)


def test_sell_fires_inside_the_dev2_dev3_zone():
    s = _strat()
    sigs = s.generate(_feat(last_price=103.0))  # between bb_upper(102) and bb3_upper(104)
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_sell_beyond_dev3_does_not_fire():
    s = _strat()
    assert s.generate(_feat(last_price=105.0)) == []   # beyond bb3_upper(104)


# ── custom_brackets: fixed 15pt TP, fractal-swing 2pt-buffer SL ───────────────

def test_buy_tp_is_fixed_15_points():
    s = _strat()
    _, tp = s.custom_brackets(Side.BUY, entry_price=100.00, symbol="EURUSD")
    assert tp == 100.00 + 15.0 * 0.0001


def test_sell_tp_is_fixed_15_points():
    s = _strat()
    _, tp = s.custom_brackets(Side.SELL, entry_price=100.00, symbol="EURUSD")
    assert tp == 100.00 - 15.0 * 0.0001


def test_buy_stop_is_fractal_low_minus_2_points():
    s = _strat()
    dip = [(100.0, 110.0), (95.0, 108.0), (85.0, 105.0), (96.0, 109.0),
           (99.0, 111.0), (101.0, 112.0), (103.0, 113.0)]
    s._entry_candles = _candles(dip)
    stop, _ = s.custom_brackets(Side.BUY, entry_price=113.0, symbol="EURUSD")
    assert stop == 85.0 - 2.0 * 0.0001


def test_sell_stop_is_fractal_high_plus_2_points():
    s = _strat()
    peak = [(80.0, 90.0), (90.0, 100.0), (105.0, 115.0), (91.0, 101.0),
            (85.0, 95.0), (83.0, 93.0), (81.0, 91.0)]
    s._entry_candles = _candles(peak)
    stop, _ = s.custom_brackets(Side.SELL, entry_price=80.0, symbol="EURUSD")
    assert stop == 115.0 + 2.0 * 0.0001


def test_no_confirmed_fractal_leaves_stop_none_tp_still_set():
    s = _strat()
    s._entry_candles = _candles([(90.0 + i, 100.0 + i) for i in range(10)])  # monotonic
    stop, tp = s.custom_brackets(Side.BUY, entry_price=200.0, symbol="EURUSD")
    assert stop is None and tp is not None


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _strat(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=100.0, symbol="EURUSD") is None


# ── Feature-store plumbing: dev3/dev4 bands are genuinely computed ────────────

def test_build_kraken_computes_wider_deviation_bands():
    closes = [100.0 + (i % 6) * 0.5 for i in range(40)]
    candles = [Candle(symbol="GBPJPY", timeframe="15m", open=c, high=c + 0.2,
                      low=c - 0.2, close=c,
                      ts=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * i))
               for i, c in enumerate(closes)]
    feats = build_kraken(symbol="GBPJPY", candles=candles)
    series = build_kraken_series("GBPJPY", candles)
    last = series[-1]
    # Wider deviations must bracket the tighter one, and single/series builds
    # roughly agree (the two builders use different std estimators — pandas
    # rolling std defaults to ddof=1, numpy's to ddof=0 — a small pre-existing
    # discrepancy shared with bb_lower/bb_upper, not something new here).
    assert feats.bb4_lower < feats.bb3_lower < feats.bb_lower
    assert feats.bb_upper < feats.bb3_upper < feats.bb4_upper
    assert feats.bb3_lower == pytest.approx(last.bb3_lower, rel=0.05)
    assert feats.bb4_upper == pytest.approx(last.bb4_upper, rel=0.05)
