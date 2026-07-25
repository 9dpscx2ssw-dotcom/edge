"""Final strategy-bank batch (25 Jul): 12 new app-spec strategies from the
last screenshot round — parsar_awesome, cci_ema_psar, ema_adx_macd_contrarian,
momentum_forex, psar_ao_ac, cci_ema_fixed, ema100_dual_tf, ichimoku_awesome,
scalp_macd_stoch_10pt, ema200_awesome, bb_williams_rsi_ranging, triple_sma.

One compact test class per strategy: entry (buy + sell + a blocking
condition), plus custom_brackets where the strategy defines one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gungnir.data.models import Candle, Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import (
    BBWilliamsRSIRangingStrategy,
    CCIEMAFixedStrategy,
    CCIEMAPSARStrategy,
    EMA100DualTFStrategy,
    EMA200AwesomeStrategy,
    EMAADXMACDContrarianStrategy,
    IchimokuAwesomeStrategy,
    MomentumForexStrategy,
    PSARAOAcStrategy,
    ParSARAwesomeStrategy,
    ScalpMACDStoch10PtStrategy,
    TripleSMAStrategy,
)


def _candles(lows_highs: list[tuple[float, float]], symbol="EURUSD", tf="1h") -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(symbol=symbol, timeframe=tf, open=(lo + hi) / 2, high=hi, low=lo,
                   close=(lo + hi) / 2, ts=start + timedelta(hours=i))
            for i, (lo, hi) in enumerate(lows_highs)]


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0)
    base.update(over)
    return KrakenFeatureSet(**base)


# ── parsar_awesome ──────────────────────────────────────────────────────────

def _psar_awe(**p) -> ParSARAwesomeStrategy:
    return ParSARAwesomeStrategy(params=p, mode="shadow", timeframe="30m")


def test_parsar_awesome_buy():
    s = _psar_awe()
    sigs = s.generate(_feat(last_price=100.0, sar=99.0, ao=0.5, prev_ao=0.2, ema5=99.5))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_parsar_awesome_sell():
    s = _psar_awe()
    sigs = s.generate(_feat(last_price=100.0, sar=101.0, ao=-0.5, prev_ao=-0.2, ema5=100.5))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_parsar_awesome_sar_wrong_side_blocks():
    s = _psar_awe()
    assert s.generate(_feat(last_price=100.0, sar=101.0, ao=0.5, prev_ao=0.2, ema5=99.5)) == []


def test_parsar_awesome_brackets_use_symbol_table():
    s = _psar_awe()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=0.97, symbol="USDCHF")
    assert tp == 0.97 + 50.0 * 0.0001
    assert stop == 0.97 - 18.0 * 0.0001


# ── cci_ema_psar ─────────────────────────────────────────────────────────────

def _cci_ema_psar(**p) -> CCIEMAPSARStrategy:
    return CCIEMAPSARStrategy(params=p, mode="shadow", timeframe="1h")


def test_cci_ema_psar_buy_on_cross_up_with_positive_cci():
    s = _cci_ema_psar()
    sigs = s.generate(_feat(ema8=10.0, prev_ema8=9.0, ema28=9.5, prev_ema28=9.5, cci30=10.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_cci_ema_psar_no_fire_when_cci_disagrees():
    s = _cci_ema_psar()
    assert s.generate(_feat(ema8=10.0, prev_ema8=9.0, ema28=9.5, prev_ema28=9.5, cci30=-10.0)) == []


def test_cci_ema_psar_exit_hooks_target_own_ema_pair():
    s = _cci_ema_psar()
    assert s.ema_cross_exit is True
    assert s.ema_cross_exit_fast == "ema8" and s.ema_cross_exit_slow == "ema28"
    assert s.trail_field == "sar"


# ── ema_adx_macd_contrarian ──────────────────────────────────────────────────

def _ema_adx_macd(**p) -> EMAADXMACDContrarianStrategy:
    return EMAADXMACDContrarianStrategy(params=p, mode="shadow", timeframe="4h")


def test_contrarian_buy_on_down_cross_negative_macd():
    s = _ema_adx_macd()
    sigs = s.generate(_feat(ema4=9.0, prev_ema4=11.0, ema10=10.0, prev_ema10=10.0,
                            macd_5_10=-0.5, minus_di28=20.0, plus_di28=10.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_contrarian_sell_on_up_cross_positive_macd():
    s = _ema_adx_macd()
    sigs = s.generate(_feat(ema4=11.0, prev_ema4=9.0, ema10=10.0, prev_ema10=10.0,
                            macd_5_10=0.5, plus_di28=20.0, minus_di28=10.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_contrarian_brackets_per_symbol_table():
    s = _ema_adx_macd()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.10, symbol="GBPUSD")
    assert tp == 1.10 + 70.0 * 0.0001
    assert stop == 1.10 - (70.0 / 3.0) * 0.0001


def test_contrarian_unknown_timeframe_falls_back_to_generic():
    s = EMAADXMACDContrarianStrategy(params={}, mode="shadow", timeframe="15m")
    assert s.custom_brackets(Side.BUY, entry_price=1.10, symbol="EURUSD") is None


# ── momentum_forex ───────────────────────────────────────────────────────────

def _momentum_forex(**p) -> MomentumForexStrategy:
    return MomentumForexStrategy(params=p, mode="shadow", timeframe="15m")


def test_momentum_forex_buy():
    s = _momentum_forex()
    sigs = s.generate(_feat(last_price=101.0, momentum30=101.0, prev_momentum30=99.0,
                            sma11=100.5, sma21=100.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_momentum_forex_sell():
    s = _momentum_forex()
    sigs = s.generate(_feat(last_price=99.0, momentum30=99.0, prev_momentum30=101.0,
                            sma11=99.5, sma21=100.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_momentum_forex_price_below_mas_blocks_buy():
    s = _momentum_forex()
    assert s.generate(_feat(last_price=99.0, momentum30=101.0, prev_momentum30=99.0,
                            sma11=100.5, sma21=100.0)) == []


def test_momentum_forex_uses_rsi_exhaustion_exit():
    s = _momentum_forex()
    assert s.rsi_exhaustion_exit is True


# ── psar_ao_ac ───────────────────────────────────────────────────────────────

def _psar_ao_ac(**p) -> PSARAOAcStrategy:
    return PSARAOAcStrategy(params=p, mode="shadow", timeframe="1h")


def test_psar_ao_ac_buy_all_three_green():
    s = _psar_ao_ac()
    candles = _candles([(98.0, 100.0)])
    sigs = s.generate(_feat(last_price=100.0, sar=99.0, ao=0.5, prev_ao=0.2,
                            ac=0.1, prev_ac=0.05, candles=candles))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_psar_ao_ac_no_fire_if_ac_not_confirming():
    s = _psar_ao_ac()
    candles = _candles([(98.0, 100.0)])
    assert s.generate(_feat(last_price=100.0, sar=99.0, ao=0.5, prev_ao=0.2,
                            ac=0.05, prev_ac=0.1, candles=candles)) == []


def test_psar_ao_ac_brackets_sl_at_signal_candle_low():
    s = _psar_ao_ac()
    candles = _candles([(98.0, 100.0)])
    s.generate(_feat(last_price=100.0, sar=99.0, ao=0.5, prev_ao=0.2,
                     ac=0.1, prev_ac=0.05, candles=candles))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=100.0, symbol="EURUSD")
    assert stop == 98.0
    assert tp == 100.0 + (100.0 - 98.0)


# ── cci_ema_fixed ────────────────────────────────────────────────────────────

def _cci_ema_fixed(**p) -> CCIEMAFixedStrategy:
    return CCIEMAFixedStrategy(params=p, mode="shadow", timeframe="30m")


def test_cci_ema_fixed_buy():
    s = _cci_ema_fixed()
    sigs = s.generate(_feat(ema8=10.0, prev_ema8=9.0, ema28=9.5, prev_ema28=9.5, cci30=10.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_cci_ema_fixed_brackets_asymmetric_sl():
    s = _cci_ema_fixed()
    stop_buy, tp_buy = s.custom_brackets(Side.BUY, entry_price=1.10, symbol="EURUSD")
    stop_sell, tp_sell = s.custom_brackets(Side.SELL, entry_price=1.10, symbol="EURUSD")
    assert stop_buy == 1.10 - 20.0 * 0.0001
    assert stop_sell == 1.10 + 10.0 * 0.0001
    assert tp_buy == 1.10 + 50.0 * 0.0001 and tp_sell == 1.10 - 50.0 * 0.0001


# ── ema100_dual_tf ───────────────────────────────────────────────────────────

def _ema100_dual(**p) -> EMA100DualTFStrategy:
    return EMA100DualTFStrategy(params=p, mode="shadow", timeframe="15m")


def test_ema100_dual_tf_buy_requires_h1_confirmation():
    s = _ema100_dual()
    s._confirm_features = _feat(ema5=105.0, ema100=100.0)
    sigs = s.generate(_feat(ema5=101.0, prev_ema5=99.0, ema100=100.0, prev_ema100=100.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_ema100_dual_tf_no_confirm_features_blocks():
    s = _ema100_dual()
    assert s.generate(_feat(ema5=101.0, prev_ema5=99.0, ema100=100.0, prev_ema100=100.0)) == []


def test_ema100_dual_tf_h1_disagreement_blocks():
    s = _ema100_dual()
    s._confirm_features = _feat(ema5=95.0, ema100=100.0)   # H1 says downtrend
    assert s.generate(_feat(ema5=101.0, prev_ema5=99.0, ema100=100.0, prev_ema100=100.0)) == []


def test_ema100_dual_tf_brackets_fixed_points():
    s = _ema100_dual()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.10, symbol="EURUSD")
    assert stop == 1.10 - 10.0 * 0.0001
    assert tp == 1.10 + 30.0 * 0.0001


# ── ichimoku_awesome ─────────────────────────────────────────────────────────

def _ichimoku_awesome(**p) -> IchimokuAwesomeStrategy:
    return IchimokuAwesomeStrategy(params=p, mode="shadow", timeframe="1h")


def test_ichimoku_awesome_buy():
    s = _ichimoku_awesome()
    candles = _candles([(90.0, 100.0), (91.0, 101.0), (89.0, 103.0), (92.0, 104.0), (93.0, 105.0)])
    sigs = s.generate(_feat(last_price=105.0, senkou_b=98.0, ao=0.5, prev_ao=0.2, candles=candles))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_ichimoku_awesome_no_candles_blocks():
    s = _ichimoku_awesome()
    assert s.generate(_feat(last_price=105.0, senkou_b=98.0, ao=0.5, prev_ao=0.2)) == []


def test_ichimoku_awesome_brackets_use_swing_low():
    s = _ichimoku_awesome(swing_order=1.0)
    candles = _candles([(90.0, 100.0), (91.0, 101.0), (85.0, 103.0), (92.0, 104.0), (93.0, 105.0)])
    s.generate(_feat(last_price=105.0, senkou_b=98.0, ao=0.5, prev_ao=0.2, candles=candles))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=105.0, symbol="EURUSD")
    assert stop == 85.0 - 5.0 * 0.0001


# ── scalp_macd_stoch_10pt ────────────────────────────────────────────────────

def _scalp_10pt(**p) -> ScalpMACDStoch10PtStrategy:
    return ScalpMACDStoch10PtStrategy(params=p, mode="shadow", timeframe="1m")


def test_scalp_10pt_buy_on_stoch_recovery():
    s = _scalp_10pt()
    candles = _candles([(98.0, 100.0)])
    sigs = s.generate(_feat(macd_hist_13_26=0.001, prev_stoch5_k=15.0, stoch5_k=25.0,
                            prev_stoch5_d=50.0, stoch5_d=50.0, candles=candles))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_scalp_10pt_negative_macd_blocks_buy():
    s = _scalp_10pt()
    candles = _candles([(98.0, 100.0)])
    assert s.generate(_feat(macd_hist_13_26=-0.001, prev_stoch5_k=15.0, stoch5_k=25.0,
                            candles=candles)) == []


def test_scalp_10pt_brackets_flat_10_points():
    s = _scalp_10pt()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.10, symbol="EURUSD")
    assert tp == 1.10 + 10.0 * 0.0001


# ── ema200_awesome ───────────────────────────────────────────────────────────

def _ema200_awesome(**p) -> EMA200AwesomeStrategy:
    return EMA200AwesomeStrategy(params=p, mode="shadow", timeframe="1h")


def test_ema200_awesome_buy():
    s = _ema200_awesome()
    sigs = s.generate(_feat(last_price=105.0, ema200=100.0, ao=0.5, prev_ao=0.2))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_ema200_awesome_price_below_ema_blocks_buy():
    s = _ema200_awesome()
    assert s.generate(_feat(last_price=95.0, ema200=100.0, ao=0.5, prev_ao=0.2)) == []


def test_ema200_awesome_brackets_need_swing_and_candles():
    s = _ema200_awesome(swing_order=1.0)
    candles = _candles([(90.0, 100.0), (91.0, 101.0), (85.0, 103.0), (92.0, 104.0), (93.0, 105.0)])
    s.generate(_feat(last_price=105.0, ema200=100.0, ao=0.5, prev_ao=0.2, candles=candles))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=105.0, symbol="EURUSD")
    assert stop == 85.0 - 5.0 * 0.0001


# ── bb_williams_rsi_ranging ──────────────────────────────────────────────────

def _bb_williams_rsi(**p) -> BBWilliamsRSIRangingStrategy:
    return BBWilliamsRSIRangingStrategy(params=p, mode="shadow", timeframe="15m")


def test_bb_williams_rsi_buy():
    s = _bb_williams_rsi()
    sigs = s.generate(_feat(last_price=98.0, bb_lower=98.0, bb_mid=100.0,
                            prev_rsi5=25.0, rsi5=32.0,
                            prev_williams_r25=-85.0, williams_r25=-70.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_bb_williams_rsi_sell():
    s = _bb_williams_rsi()
    sigs = s.generate(_feat(last_price=102.0, bb_upper=102.0, bb_mid=100.0,
                            prev_rsi5=75.0, rsi5=68.0,
                            prev_williams_r25=-15.0, williams_r25=-30.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_bb_williams_rsi_price_off_band_blocks():
    s = _bb_williams_rsi()
    assert s.generate(_feat(last_price=100.0, bb_lower=98.0, bb_mid=100.0,
                            prev_rsi5=25.0, rsi5=32.0,
                            prev_williams_r25=-85.0, williams_r25=-70.0)) == []


def test_bb_williams_rsi_brackets_tp_at_bb_mid():
    s = _bb_williams_rsi()
    s.generate(_feat(last_price=98.0, bb_lower=98.0, bb_mid=100.0,
                     prev_rsi5=25.0, rsi5=32.0,
                     prev_williams_r25=-85.0, williams_r25=-70.0))
    stop, tp = s.custom_brackets(Side.BUY, entry_price=98.0, symbol="EURUSD")
    assert tp == 100.0
    assert stop == 98.0 - 3.0 * 0.0001


# ── triple_sma ───────────────────────────────────────────────────────────────

def _triple_sma(**p) -> TripleSMAStrategy:
    return TripleSMAStrategy(params=p, mode="shadow", timeframe="4h")


def test_triple_sma_buy():
    s = _triple_sma()
    sigs = s.generate(_feat(sma26=101.0, prev_sma26=99.0, sma100=100.0, prev_sma100=100.0,
                            sma13=102.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_triple_sma_sma13_not_above_both_blocks():
    s = _triple_sma()
    assert s.generate(_feat(sma26=101.0, prev_sma26=99.0, sma100=100.0, prev_sma100=100.0,
                            sma13=100.5)) == []


def test_triple_sma_exit_targets_sma13_sma26():
    s = _triple_sma()
    assert s.ema_cross_exit is True
    assert s.ema_cross_exit_fast == "sma13" and s.ema_cross_exit_slow == "sma26"
