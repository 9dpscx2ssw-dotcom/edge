"""bb_rsi / bb_rsi_m30: source app "Bollinger Bands and RSI" strategy.

Entry was already faithful (RSI>70 + price>upper band for longs, mirror for
shorts — a momentum-continuation rule, not mean-reversion, despite the
70/30 zones). This guards the two gaps fixed on top of that: a genuine
RSI(11) feature (previously every strategy shared one hardcoded RSI(14)),
and the app's fixed-points TP table split across its two listed timeframes
(M15/M30), registered as separate strategies per the user's instruction to
treat each timeframe as its own strategy — mirroring the existing
hma_dc_* per-timeframe pattern.
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import (
    KrakenFeatureSet,
    build_kraken,
    build_kraken_series,
)
from gungnir.strategy.kraken_strategies import BBRSIM30Strategy, BBRSIStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, bb_upper=99.0, bb_lower=101.0,
                rsi11=75.0, rsi=50.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _m15(**params) -> BBRSIStrategy:
    return BBRSIStrategy(params=params, mode="shadow", timeframe="15m")


def _m30(**params) -> BBRSIM30Strategy:
    return BBRSIM30Strategy(params=params, mode="shadow", timeframe="30m")


# ── Entry: breakout-continuation, using RSI(11) not the shared RSI(14) ────────

def test_buy_requires_rsi11_overbought_and_price_above_upper_band():
    s = _m15()
    sigs = s.generate(_feat(last_price=100.0, bb_upper=99.0, rsi11=75.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_requires_rsi11_oversold_and_price_below_lower_band():
    s = _m15()
    sigs = s.generate(_feat(last_price=100.0, bb_lower=101.0, rsi11=25.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_uses_rsi11_field_not_the_shared_rsi14():
    # rsi (the shared 14-period field) disagrees with rsi11 — entry must
    # follow rsi11, the app's actual spec.
    s = _m15()
    sigs = s.generate(_feat(last_price=100.0, bb_upper=99.0, rsi11=75.0, rsi=40.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_price_inside_bands_never_fires_even_if_rsi_extreme():
    s = _m15()
    assert s.generate(_feat(last_price=100.0, bb_upper=105.0, bb_lower=95.0,
                            rsi11=80.0)) == []


def test_m15_and_m30_share_identical_entry_logic():
    feat = _feat(last_price=100.0, bb_upper=99.0, rsi11=75.0)
    m15_sigs = _m15().generate(feat)
    m30_sigs = _m30().generate(feat)
    assert len(m15_sigs) == len(m30_sigs) == 1
    assert m15_sigs[0].side == m30_sigs[0].side == Side.BUY


def test_bb_rsi_m30_registers_its_own_name():
    assert BBRSIStrategy.name == "bb_rsi"
    assert BBRSIM30Strategy.name == "bb_rsi_m30"


# ── custom_brackets: the app's fixed-points TP table + flat 10pt SL ────────────

def test_m15_eurusd_brackets_match_app_table():
    s = _m15()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 - 10.0 * 0.0001
    assert tp == 1.1000 + 15.0 * 0.0001


def test_m15_gbpusd_brackets_match_app_table():
    s = _m15()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.2500, symbol="GBPUSD")
    assert tp == 1.2500 + 19.0 * 0.0001


def test_m30_eurusd_brackets_match_app_table():
    s = _m30()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert tp == 1.1000 + 19.0 * 0.0001


def test_m30_gbpusd_brackets_match_app_table():
    s = _m30()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.2500, symbol="GBPUSD")
    assert tp == 1.2500 + 25.0 * 0.0001


def test_sell_brackets_invert_direction():
    s = _m15()
    stop, tp = s.custom_brackets(Side.SELL, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 + 10.0 * 0.0001
    assert tp == 1.1000 - 15.0 * 0.0001


def test_symbol_outside_app_table_falls_back_to_generic_atr():
    # AUDUSD isn't in the app's named table for either timeframe.
    s = _m15()
    assert s.custom_brackets(Side.BUY, entry_price=0.65, symbol="AUDUSD") is None


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _m15()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _m15(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD") is None


# ── Feature-store plumbing: rsi11 is genuinely a separate computation ─────────

def test_build_kraken_computes_distinct_rsi11():
    closes = [100.0 + (i % 6) * 0.4 for i in range(30)]
    from datetime import datetime, timedelta, timezone
    from gungnir.data.models import Candle
    candles = [Candle(symbol="EURUSD", timeframe="15m", open=c, high=c + 0.1,
                      low=c - 0.1, close=c,
                      ts=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * i))
               for i, c in enumerate(closes)]
    feats = build_kraken(symbol="EURUSD", candles=candles)
    series = build_kraken_series("EURUSD", candles)
    assert feats.rsi11 == series[-1].rsi11
    # A shorter (11 vs 14) lookback reacts faster -> not identical to rsi14
    # for a wiggling series (equal only in degenerate/flat cases).
    assert feats.rsi11 != feats.rsi
