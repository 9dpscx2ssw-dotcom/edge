"""bb_macd_sma_app: faithful replica of the source "BB, MACD, MA" app strategy.

Guards the 25 Jul addition of this strategy as a SEPARATE variant from
`bb_macd_sma` — that strategy's MACD condition was deliberately inverted from
the app spec after the literal version scored a 1.8% win rate over 228 live
trades (audit F-16). This variant restores the unmodified app rule (SMMA(2)
crosses the BB mid-line while the MACD(11,27,4) histogram still disagrees) so
it can be shadow-vetted on its own, plus a 2-bar freshness window that lets
the crossover and histogram conditions land up to one bar apart.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet, build_kraken, build_kraken_series
from gungnir.strategy.kraken_strategies import BBMACDSMAppStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, bb_mid=100.0, bb_upper=102.0,
                smma2=100.0, prev_smma2=100.0, prev_bb_mid=100.0,
                macd_hist_11_27=0.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat() -> BBMACDSMAppStrategy:
    return BBMACDSMAppStrategy(mode="shadow", timeframe="15m")


# ── Entry: crossover + contrarian histogram, both on the same bar ─────────────

def test_buy_fires_on_cross_up_with_histogram_still_negative():
    s = _strat()
    sigs = s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                            smma2=101.0, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_fires_on_cross_down_with_histogram_still_positive():
    s = _strat()
    sigs = s.generate(_feat(prev_smma2=101.0, prev_bb_mid=100.0,
                            smma2=99.0, bb_mid=100.0, macd_hist_11_27=0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_no_cross_no_signal():
    s = _strat()
    assert s.generate(_feat(prev_smma2=101.0, prev_bb_mid=100.0,
                            smma2=101.5, bb_mid=100.0, macd_hist_11_27=-0.001)) == []


def test_cross_up_with_histogram_already_positive_does_not_fire_immediately():
    # Momentum already agrees with the new direction — not the app's
    # contrarian setup — so it must wait for the freshness window, not fire.
    s = _strat()
    assert s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                            smma2=101.0, bb_mid=100.0, macd_hist_11_27=0.001)) == []


# ── Freshness window: cross bar + 1 more, then expire ──────────────────────────

def test_histogram_confirming_one_bar_later_still_fires():
    s = _strat()
    # Bar 0: cross up, histogram hasn't flipped negative yet — no fire.
    assert s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                            smma2=101.0, bb_mid=100.0, macd_hist_11_27=0.001)) == []
    # Bar 1 (still within the freshness window): no new cross, still on the
    # buy side, histogram now negative — fires.
    sigs = s.generate(_feat(prev_smma2=101.0, prev_bb_mid=100.0,
                            smma2=101.2, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_freshness_window_expires_after_two_bars():
    s = _strat()
    # Bar 0: cross up, histogram doesn't confirm.
    s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                     smma2=101.0, bb_mid=100.0, macd_hist_11_27=0.001))
    # Bar 1: still doesn't confirm (uses up the freshness window).
    s.generate(_feat(prev_smma2=101.0, prev_bb_mid=100.0,
                     smma2=101.2, bb_mid=100.0, macd_hist_11_27=0.001))
    # Bar 2: histogram finally confirms, but the window has expired — no fire.
    sigs = s.generate(_feat(prev_smma2=101.2, prev_bb_mid=100.0,
                            smma2=101.3, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert sigs == []


def test_pending_invalidated_if_price_recrosses_before_confirming():
    s = _strat()
    # Bar 0: cross up, no confirm yet.
    s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                     smma2=101.0, bb_mid=100.0, macd_hist_11_27=0.001))
    # Bar 1: price falls back under the mid-line (no formal down-cross this
    # bar — prev_smma2 < prev_bb_mid keeps _crossed_down from firing — but the
    # BUY setup is no longer "on the buy side" and must be dropped).
    sigs = s.generate(_feat(prev_smma2=99.9, prev_bb_mid=100.0,
                            smma2=99.0, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert sigs == []
    # Bar 2: even though the histogram still agrees, the setup is gone — a
    # fresh cross is required, not a resurrection of the old one.
    sigs = s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                            smma2=99.0, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert sigs == []


def test_consumed_signal_does_not_refire_next_bar():
    s = _strat()
    sigs = s.generate(_feat(prev_smma2=99.0, prev_bb_mid=100.0,
                            smma2=101.0, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert len(sigs) == 1
    # Same still-crossed state next bar, no new cross — already consumed.
    sigs2 = s.generate(_feat(prev_smma2=101.0, prev_bb_mid=100.0,
                             smma2=101.2, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert sigs2 == []


def test_pending_state_is_per_symbol():
    s = _strat()
    # EURUSD crosses without confirming.
    s.generate(_feat(symbol="EURUSD", prev_smma2=99.0, prev_bb_mid=100.0,
                     smma2=101.0, bb_mid=100.0, macd_hist_11_27=0.001))
    # GBPUSD, unrelated: no cross, no pending state, no signal — and EURUSD's
    # pending entry must be untouched by this call.
    assert s.generate(_feat(symbol="GBPUSD", prev_smma2=101.0, prev_bb_mid=100.0,
                            smma2=101.5, bb_mid=100.0, macd_hist_11_27=-0.001)) == []
    sigs = s.generate(_feat(symbol="EURUSD", prev_smma2=101.0, prev_bb_mid=100.0,
                            smma2=101.2, bb_mid=100.0, macd_hist_11_27=-0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


# ── Feature-store plumbing: smma2 / prev_smma2 / prev_bb_mid / macd_hist_11_27 ─

def _candles(closes: list[float]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol="EURUSD", timeframe="15m", open=c, high=c + 0.1,
                   low=c - 0.1, close=c, ts=start + timedelta(minutes=15 * i))
            for i, c in enumerate(closes)]


def test_build_kraken_series_populates_new_fields():
    closes = [100.0 + (i % 5) * 0.3 for i in range(40)]
    series = build_kraken_series("EURUSD", _candles(closes))
    last = series[-1]
    assert isinstance(last, KrakenFeatureSet)
    # smma2 should sit close to price (period-2 smoothing), not stuck at 0.
    assert last.smma2 != 0.0
    # prev_smma2 must actually be the smma2 value one bar earlier.
    assert series[-2].smma2 == last.prev_smma2
    assert series[-2].bb_mid == last.prev_bb_mid
    # Histogram is a real (line - signal) value, independent of macd_11_27.
    assert isinstance(last.macd_hist_11_27, float)


def test_build_kraken_single_bar_matches_series_tail():
    closes = [100.0 + (i % 7) * 0.2 for i in range(40)]
    candles = _candles(closes)
    series = build_kraken_series("EURUSD", candles)
    single = build_kraken(symbol="EURUSD", candles=candles)
    last = series[-1]
    assert single.smma2 == pytest.approx(last.smma2, rel=1e-6)
    assert single.prev_smma2 == pytest.approx(last.prev_smma2, rel=1e-6)
    assert single.prev_bb_mid == pytest.approx(last.prev_bb_mid, rel=1e-6)
    assert single.macd_hist_11_27 == pytest.approx(last.macd_hist_11_27, rel=1e-6)
