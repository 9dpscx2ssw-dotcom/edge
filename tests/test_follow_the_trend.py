"""follow_the_trend_h4 / follow_the_trend_d1: faithful replica of the
source "Follow the Trend" app strategy, registered per timeframe (each has
its own TP in the app's exit table) — same pattern as bb_rsi/bb_rsi_m30.
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import (
    FollowTheTrendD1Strategy,
    FollowTheTrendH4Strategy,
)


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0,
                ema4=101.0, ema10=100.0, prev_ema4=99.0, prev_ema10=100.0,
                plus_di28=25.0, minus_di28=15.0, macd_5_10=0.001, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _h4(**params) -> FollowTheTrendH4Strategy:
    return FollowTheTrendH4Strategy(params=params, mode="shadow", timeframe="4h")


def _d1(**params) -> FollowTheTrendD1Strategy:
    return FollowTheTrendD1Strategy(params=params, mode="shadow", timeframe="1d")


# ── Entry: DI dominance + EMA(4,10) cross + MACD(5,10,4) sign ──────────────────

def test_buy_requires_all_three_conditions():
    s = _h4()
    sigs = s.generate(_feat(prev_ema4=99.0, prev_ema10=100.0, ema4=101.0, ema10=100.0,
                            plus_di28=25.0, minus_di28=15.0, macd_5_10=0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_requires_all_three_conditions():
    s = _h4()
    sigs = s.generate(_feat(prev_ema4=101.0, prev_ema10=100.0, ema4=99.0, ema10=100.0,
                            plus_di28=15.0, minus_di28=25.0, macd_5_10=-0.001))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_no_ema_cross_blocks_entry_even_if_di_and_macd_agree():
    s = _h4()
    # ema4 already above ema10 last bar too -> no crossover this bar.
    assert s.generate(_feat(prev_ema4=101.0, prev_ema10=100.0, ema4=102.0, ema10=100.0,
                            plus_di28=25.0, minus_di28=15.0, macd_5_10=0.001)) == []


def test_di_disagreement_blocks_entry():
    s = _h4()
    assert s.generate(_feat(prev_ema4=99.0, prev_ema10=100.0, ema4=101.0, ema10=100.0,
                            plus_di28=15.0, minus_di28=25.0, macd_5_10=0.001)) == []


def test_macd_wrong_sign_blocks_entry():
    s = _h4()
    assert s.generate(_feat(prev_ema4=99.0, prev_ema10=100.0, ema4=101.0, ema10=100.0,
                            plus_di28=25.0, minus_di28=15.0, macd_5_10=-0.001)) == []


def test_h4_and_d1_share_identical_entry_logic():
    feat = _feat(prev_ema4=99.0, prev_ema10=100.0, ema4=101.0, ema10=100.0,
                 plus_di28=25.0, minus_di28=15.0, macd_5_10=0.001)
    assert len(_h4().generate(feat)) == len(_d1().generate(feat)) == 1


# ── custom_brackets: per-timeframe TP, SL = TP/3 ───────────────────────────────

def test_h4_tp_is_60_points_sl_is_a_third():
    s = _h4()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert tp == 1.1000 + 60.0 * 0.0001
    assert stop == 1.1000 - (60.0 / 3.0) * 0.0001


def test_d1_tp_is_200_points_sl_is_a_third():
    s = _d1()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert tp == 1.1000 + 200.0 * 0.0001
    assert stop == 1.1000 - (200.0 / 3.0) * 0.0001


def test_sell_brackets_invert_direction():
    s = _h4()
    stop, tp = s.custom_brackets(Side.SELL, entry_price=1.1000, symbol="EURUSD")
    assert tp == 1.1000 - 60.0 * 0.0001
    assert stop == 1.1000 + (60.0 / 3.0) * 0.0001


def test_non_fx_symbol_falls_back_to_generic_atr():
    s = _h4()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off():
    s = _h4(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD") is None


def test_names_are_distinct():
    assert FollowTheTrendH4Strategy.name == "follow_the_trend_h4"
    assert FollowTheTrendD1Strategy.name == "follow_the_trend_d1"
