"""cci_reversal: overwritten in place to match the source "CCI strategy" app
spec — a momentum-confirmation reversal (buy CONFIRMED overbought strength
after a prior oversold touch), not a single-threshold contrarian trigger.

This one mattered more than the other overwrites: the prior version ran
`mode: shadow` in the curated live pool with its entry direction literally
inverted from the app (bought oversold instead of confirmed-overbought-
after-oversold), and its live-shadow track record (29% win, -31.2 pnl) is
consistent with that inversion.
"""

from __future__ import annotations

from gungnir.data.models import Side
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.strategy.kraken_strategies import CCIReversalStrategy


def _feat(cci=0.0, symbol="EURUSD") -> KrakenFeatureSet:
    return KrakenFeatureSet(symbol=symbol, last_price=1.1000, cci14=cci, atr=0.001)


def _strat(**params) -> CCIReversalStrategy:
    return CCIReversalStrategy(params=params, mode="shadow", timeframe="1h")


# ── Entry: two-phase reversal confirmation, not a single threshold ────────────

def test_buy_requires_overbought_after_a_prior_oversold_touch():
    s = _strat()
    assert s.generate(_feat(-160.0)) == []          # touches oversold: arms, no fire
    sigs = s.generate(_feat(160.0))                  # now overbought: confirmed reversal
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_sell_requires_oversold_after_a_prior_overbought_touch():
    s = _strat()
    assert s.generate(_feat(160.0)) == []
    sigs = s.generate(_feat(-160.0))
    assert len(sigs) == 1 and sigs[0].side == Side.SELL


def test_oversold_touch_alone_never_buys_the_dip():
    # The old (inverted) logic bought here. The app buys strength, not the
    # dip itself — a bare oversold touch with no prior overbought must not fire.
    s = _strat()
    assert s.generate(_feat(-160.0)) == []


def test_overbought_touch_alone_never_sells_the_rip():
    s = _strat()
    assert s.generate(_feat(160.0)) == []


def test_state_persists_through_mid_zone_bars():
    s = _strat()
    s.generate(_feat(-160.0))     # oversold: armed
    s.generate(_feat(0.0))        # mid-zone: state must be retained, not cleared
    sigs = s.generate(_feat(160.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_confirmation_is_self_consuming():
    s = _strat()
    s.generate(_feat(-160.0))
    sigs1 = s.generate(_feat(160.0))
    assert len(sigs1) == 1
    # Still overbought next bar — no fresh oversold touch since the last
    # confirmed buy, so it must not refire.
    sigs2 = s.generate(_feat(165.0))
    assert sigs2 == []


def test_a_fresh_oversold_touch_rearms_after_consumption():
    s = _strat()
    s.generate(_feat(-160.0))
    s.generate(_feat(160.0))       # consumed
    s.generate(_feat(-160.0))      # rearm
    sigs = s.generate(_feat(160.0))
    assert len(sigs) == 1 and sigs[0].side == Side.BUY


def test_state_is_tracked_per_symbol():
    s = _strat()
    s.generate(_feat(-160.0, symbol="EURUSD"))
    # GBPUSD has no prior oversold touch of its own — must not borrow EURUSD's.
    assert s.generate(_feat(160.0, symbol="GBPUSD")) == []
    sigs = s.generate(_feat(160.0, symbol="EURUSD"))
    assert len(sigs) == 1


def test_threshold_defaults_to_the_app_spec_150():
    s = _strat()
    assert s.generate(_feat(-140.0)) == []   # below 150 -> not oversold yet
    assert s.p("cci_threshold") == 150.0


# ── custom_brackets: fixed points TP/SL ────────────────────────────────────────

def test_buy_brackets_use_fixed_points_from_app_spec():
    s = _strat()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 - 5.0 * 0.0001
    assert tp == 1.1000 + 17.5 * 0.0001


def test_sell_brackets_use_fixed_points_from_app_spec():
    s = _strat()
    stop, tp = s.custom_brackets(Side.SELL, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 + 5.0 * 0.0001
    assert tp == 1.1000 - 17.5 * 0.0001


def test_brackets_use_jpy_point_size():
    s = _strat()
    stop, tp = s.custom_brackets(Side.BUY, entry_price=150.00, symbol="USDJPY")
    assert stop == 150.00 - 5.0 * 0.01
    assert tp == 150.00 + 17.5 * 0.01


def test_brackets_fall_back_to_generic_atr_for_non_fx_symbol():
    s = _strat()
    assert s.custom_brackets(Side.BUY, entry_price=15000.0, symbol="US100") is None


def test_fixed_exit_toggle_off_falls_back_to_generic_atr():
    s = _strat(fixed_exit_enabled=0.0)
    assert s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD") is None


def test_custom_tp_sl_params_are_tunable():
    s = _strat(tp_points=20.0, sl_points=3.0)
    stop, tp = s.custom_brackets(Side.BUY, entry_price=1.1000, symbol="EURUSD")
    assert stop == 1.1000 - 3.0 * 0.0001
    assert tp == 1.1000 + 20.0 * 0.0001
