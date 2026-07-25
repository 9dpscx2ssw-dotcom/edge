"""parsar_cci_ema_m1 / parsar_cci_ema_m5: SAR-vs-EMA entry, rebuilt (25 Jul)
as two independent per-timeframe strategies instead of one M1-primary
strategy with an M5 higher-timeframe confirmation fetch.

The source app spec ("Scalping with Parabolic SAR + CCI") assigns EMA50 to
M1 and EMA21 to M5 in its own indicator list — read literally, that's two
self-contained single-timeframe setups sharing one CCI/SAR entry shape, not
one signal confirmed by the other. Each variant below reads only its own
timeframe's EMA; there's no cross-timeframe fetch or `_confirm_features`
state involved anymore.
"""

from __future__ import annotations

from gungnir.core.agent import _ema_trailing_stop
from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import ParSARCCIM1Strategy, ParSARCCIM5Strategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, sar=99.0, ema50=98.0,
                ema21=98.0, cci45=150.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _m1(**params) -> ParSARCCIM1Strategy:
    return ParSARCCIM1Strategy(params=params, mode="shadow", timeframe="1m")


def _m5(**params) -> ParSARCCIM5Strategy:
    return ParSARCCIM5Strategy(params=params, mode="shadow", timeframe="5m")


# ── SAR-vs-EMA entry (not price-vs-EMA), per timeframe's own EMA ──────────────

def test_m1_buy_requires_sar_above_its_own_ema50():
    s = _m1()
    sigs = s.generate(_feat(sar=99.0, ema50=98.0, cci45=150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_m1_sell_requires_sar_below_its_own_ema50():
    s = _m1()
    sigs = s.generate(_feat(sar=97.0, ema50=98.0, cci45=-150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_m5_buy_requires_sar_above_its_own_ema21_not_ema50():
    s = _m5()
    # ema50 alone disagrees with SAR here — must not matter to the M5 variant.
    sigs = s.generate(_feat(sar=99.0, ema21=98.0, ema50=110.0, cci45=150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_m5_sell_requires_sar_below_its_own_ema21():
    s = _m5()
    sigs = s.generate(_feat(sar=97.0, ema21=98.0, cci45=-150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_sar_below_ema_blocks_buy_even_if_price_is_above_ema():
    # Price above EMA is not sufficient — SAR must itself sit above the line.
    s = _m1()
    sigs = s.generate(_feat(last_price=105.0, sar=97.0, ema50=98.0, cci45=150.0))
    assert sigs == []


def test_cci_inside_threshold_band_blocks_entry():
    s = _m1()
    assert s.generate(_feat(sar=99.0, ema50=98.0, cci45=50.0)) == []


def test_no_cross_timeframe_state_involved():
    # There's no confirm_timeframe / _confirm_features on either variant —
    # the rebuild removed the higher-timeframe-confirmation mechanism
    # entirely rather than just defaulting it off.
    assert ParSARCCIM1Strategy.confirm_timeframe == ""
    assert ParSARCCIM5Strategy.confirm_timeframe == ""


# ── Each variant is genuinely single-timeframe ─────────────────────────────────

def test_m1_and_m5_have_distinct_names_and_ema_periods():
    assert ParSARCCIM1Strategy.name == "parsar_cci_ema_m1"
    assert ParSARCCIM5Strategy.name == "parsar_cci_ema_m5"
    assert ParSARCCIM1Strategy.ema_period == 50
    assert ParSARCCIM5Strategy.ema_period == 21


def test_m1_ignores_ema21_entirely():
    s = _m1()
    # SAR agrees with ema21 but not ema50 -> the M1 variant must still block.
    sigs = s.generate(_feat(sar=99.0, ema50=110.0, ema21=98.0, cci45=150.0))
    assert sigs == []


# ── Strategy-declared trailing exit hook, matched to each variant's own EMA ────

def test_m1_trails_its_own_ema50():
    s = _m1()
    assert s.trail_ema_period == 50


def test_m5_trails_its_own_ema21():
    s = _m5()
    assert s.trail_ema_period == 21


def test_ema_trail_helper_ratchets_stop_to_the_ema_line():
    # Sanity-check the exact mechanism Agent._manage_exits drives for these
    # strategies: stop -> current EMA value, one-way tightening only.
    assert _ema_trailing_stop(Side.BUY, ema_value=101.0, cur_stop=99.0) == 101.0
    assert _ema_trailing_stop(Side.BUY, ema_value=97.0, cur_stop=99.0) is None
