"""Breakeven exit ratchet + shipped regime-rule policy validation.

Covers the two changes from the 21–22 Jul strategy review:
  * Phase 2 — `_breakeven_stop` pulls a winner's stop to entry once it has run
    `trigger_r` of its initial risk, so a >=1R winner can't round-trip to a loss.
  * Phase 1 — the `regime_rules` shipped in `config/config.example.yaml` actually
    veto the intended (family, regime) buckets under `enforce` (guards YAML typos).
"""

from __future__ import annotations

from pathlib import Path

from gungnir.config import Config
from gungnir.core import filters
from gungnir.core.agent import _breakeven_stop, _trailing_stop
from gungnir.core.filters import FilterConfig
from gungnir.data.models import Side, Signal
from gungnir.features.feature_store import KrakenFeatureSet


# ── Phase 2: breakeven ratchet ────────────────────────────────────────────────

def test_breakeven_long_moves_stop_to_entry_after_one_r():
    # entry 100, stop 98 → R = 2.0. MFE 2.0 (price hit 102) arms breakeven.
    assert _breakeven_stop(Side.BUY, 100.0, 98.0, mfe=2.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.0) == 100.0


def test_breakeven_short_moves_stop_down_to_entry():
    # short entry 100, stop 102 → R = 2.0. MFE 2.0 (price fell to 98) arms it.
    assert _breakeven_stop(Side.SELL, 100.0, 102.0, mfe=2.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.0) == 100.0


def test_breakeven_not_armed_below_trigger():
    # only ran 0.5R in favour → no move.
    assert _breakeven_stop(Side.BUY, 100.0, 98.0, mfe=1.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.0) is None


def test_breakeven_offset_locks_profit():
    # offset 0.25R above entry on a 2.0 R trade → stop at 100.5.
    assert _breakeven_stop(Side.BUY, 100.0, 98.0, mfe=2.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.25) == 100.5


def test_breakeven_is_one_way_never_widens_risk():
    # A stop already tighter than the breakeven target must not be loosened.
    assert _breakeven_stop(Side.BUY, 100.0, 100.5, mfe=5.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.0) is None
    assert _breakeven_stop(Side.SELL, 100.0, 99.5, mfe=5.0, r0=2.0,
                           trigger_r=1.0, offset_r=0.0) is None


def test_breakeven_guards_degenerate_inputs():
    assert _breakeven_stop(Side.BUY, 100.0, None, 5.0, 2.0, 1.0, 0.0) is None   # no stop
    assert _breakeven_stop(Side.BUY, 100.0, 98.0, 5.0, 0.0, 1.0, 0.0) is None   # zero risk


# ── Phase 3: trailing ratchet ─────────────────────────────────────────────────

def test_trailing_long_follows_peak_by_atr_mult():
    # long, peak 110, ATR 2, mult 1.5 → trail to 110 - 3 = 107 (above old stop).
    assert _trailing_stop(Side.BUY, 110.0, 100.0, atr=2.0, trail_mult=1.5) == 107.0


def test_trailing_short_follows_trough_upward_in_price():
    # short, trough 90, ATR 2, mult 1.5 → trail to 90 + 3 = 93 (below old stop).
    assert _trailing_stop(Side.SELL, 90.0, 100.0, atr=2.0, trail_mult=1.5) == 93.0


def test_trailing_is_one_way_never_loosens():
    # trail level (107) is looser than an already-tightened stop (108) → no move.
    assert _trailing_stop(Side.BUY, 110.0, 108.0, atr=2.0, trail_mult=1.5) is None
    assert _trailing_stop(Side.SELL, 90.0, 92.0, atr=2.0, trail_mult=1.5) is None


def test_trailing_does_not_cap_a_runner():
    # As the peak climbs, the trail climbs with it — a runner keeps its room
    # instead of being locked at a fixed level.
    s1 = _trailing_stop(Side.BUY, 110.0, 100.0, atr=2.0, trail_mult=1.5)
    s2 = _trailing_stop(Side.BUY, 130.0, s1, atr=2.0, trail_mult=1.5)
    assert s1 == 107.0 and s2 == 127.0


def test_trailing_guards_degenerate_inputs():
    assert _trailing_stop(Side.BUY, 110.0, None, 2.0, 1.5) is None   # no stop
    assert _trailing_stop(Side.BUY, 110.0, 100.0, 0.0, 1.5) is None  # no ATR
    assert _trailing_stop(Side.BUY, 110.0, 100.0, 2.0, 0.0) is None  # mult off


# ── Phase 1: shipped regime_rules ─────────────────────────────────────────────

def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, ema_fast=101.0, ema_slow=99.0,
                rsi=55.0, atr=1.0, bb_lower=98.0, bb_mid=100.0, bb_upper=102.0, adx=30.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _sig():
    return Signal(strategy="x", symbol="EURUSD", side=Side.BUY, conviction=0.7)


def _example_filter_cfg(mode: str) -> FilterConfig:
    cfg_path = Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"
    raw = dict(Config.load(cfg_path).get("filters", default={}) or {})
    raw["regime_mode"] = mode
    return FilterConfig.from_dict(raw)


def test_example_config_ships_regime_rules():
    cfg = _example_filter_cfg("enforce")
    assert cfg.regime and cfg.regime_rules, "example config must ship an active regime policy"


def test_shipped_rules_veto_intended_buckets_under_enforce():
    cfg = _example_filter_cfg("enforce")
    # A representative avoided bucket from each family in the shipped ruleset.
    avoided = [
        ("consensus", "range_high"),      # ensemble
        ("trend_following", "range_high"),  # trend
        ("hma_dc_m5", "range_high"),      # hybrid
        ("bb_rsi", "trend_high"),         # mean_reversion
        ("scalp_ema_vwap_m1", "trend_high"),  # scalp
        ("fvg_m5", "trend_high"),         # structure
    ]
    for strat, regime in avoided:
        ok, why = filters.apply(_sig(), _feat(), strat, cfg, "EURUSD", regime=regime)
        assert (ok, why) == (False, "regime"), f"{strat}@{regime} should be vetoed"


def test_shipped_rules_allow_profitable_buckets():
    cfg = _example_filter_cfg("enforce")
    # trend_low is the only positive-expectancy regime; ensemble/trend_high was +.
    allowed = [("consensus", "trend_high"), ("hma_dc_m5", "trend_high"),
               ("trend_following", "trend_low")]
    for strat, regime in allowed:
        assert filters.apply(_sig(), _feat(), strat, cfg, "EURUSD", regime=regime)[0] is True


def test_shipped_rules_are_shadow_by_default_non_blocking():
    # As shipped (regime_mode: shadow) nothing is blocked — validation only.
    cfg = _example_filter_cfg("shadow")
    assert filters.apply(_sig(), _feat(), "consensus", cfg, "EURUSD",
                         regime="range_high") == (True, None)
