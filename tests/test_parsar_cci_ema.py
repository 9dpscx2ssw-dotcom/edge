"""parsar_cci_ema: SAR-vs-EMA entry, M5/EMA21 confluence, EMA-line trailing.

Guards the 25 Jul fix that brought the strategy in line with the source app
spec ("Scalping with Parabolic SAR + CCI"): entries compare the SAR *value*
to the EMA line (not price to EMA), optionally confirmed against a higher
timeframe's EMA21, and the stop can trail the EMA line instead of a fixed
ATR distance.
"""

from __future__ import annotations

from gungnir.core.agent import _ema_trailing_stop
from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import ParSARCCIStrategy


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, sar=99.0, ema50=98.0,
                cci45=150.0, atr=1.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _strat(**params) -> ParSARCCIStrategy:
    return ParSARCCIStrategy(params=params, mode="shadow", timeframe="1m")


# ── SAR-vs-EMA entry (not price-vs-EMA) ────────────────────────────────────────

def test_buy_requires_sar_above_ema_and_cci_above_threshold():
    s = _strat(mtf_confirm_enabled=0.0)   # isolate the SAR/CCI condition
    sigs = s.generate(_feat(sar=99.0, ema50=98.0, cci45=150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_requires_sar_below_ema_and_cci_below_negative_threshold():
    s = _strat(mtf_confirm_enabled=0.0)
    sigs = s.generate(_feat(sar=97.0, ema50=98.0, cci45=-150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_sar_below_ema_blocks_buy_even_if_price_is_above_ema():
    # Price above EMA is no longer sufficient — this is the bug the app-spec
    # comparison fixed. SAR must itself sit above the EMA line.
    s = _strat(mtf_confirm_enabled=0.0)
    sigs = s.generate(_feat(last_price=105.0, sar=97.0, ema50=98.0, cci45=150.0))
    assert sigs == []


def test_cci_inside_threshold_band_blocks_entry():
    s = _strat(mtf_confirm_enabled=0.0)
    assert s.generate(_feat(sar=99.0, ema50=98.0, cci45=50.0)) == []


# ── Higher-timeframe (M5/EMA21) confluence ─────────────────────────────────────

def test_mtf_confirm_blocks_buy_against_the_htf_trend():
    s = _strat()  # mtf_confirm_enabled defaults to 1.0
    s._confirm_features = _feat(last_price=100.0, ema21=105.0)  # price below M5 EMA21
    assert s.generate(_feat(last_price=100.0, sar=99.0, ema50=98.0, cci45=150.0)) == []


def test_mtf_confirm_allows_buy_with_the_htf_trend():
    s = _strat()
    s._confirm_features = _feat(last_price=100.0, ema21=95.0)  # price above M5 EMA21
    sigs = s.generate(_feat(last_price=100.0, sar=99.0, ema50=98.0, cci45=150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_mtf_confirm_toggle_off_ignores_confirm_features():
    s = _strat(mtf_confirm_enabled=0.0)
    s._confirm_features = _feat(last_price=100.0, ema21=105.0)  # would block if honoured
    sigs = s.generate(_feat(last_price=100.0, sar=99.0, ema50=98.0, cci45=150.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_no_confirm_features_never_blocks():
    # Confirm timeframe not fetched (thin data / not wired up) ⇒ skip the check.
    s = _strat()
    assert s._confirm_features is None
    sigs = s.generate(_feat(sar=99.0, ema50=98.0, cci45=150.0))
    assert len(sigs) == 1


# ── Strategy-declared trailing exit hook ───────────────────────────────────────

def test_strategy_declares_ema_trailing_hook():
    s = _strat()
    assert s.trail_ema_period == 50
    assert s.confirm_timeframe == "5m"


def test_ema_trail_helper_ratchets_stop_to_the_ema_line():
    # Sanity-check the exact mechanism Agent._manage_exits drives for this
    # strategy: stop -> current EMA50, one-way tightening only.
    assert _ema_trailing_stop(Side.BUY, ema_value=101.0, cur_stop=99.0) == 101.0
    assert _ema_trailing_stop(Side.BUY, ema_value=97.0, cur_stop=99.0) is None
