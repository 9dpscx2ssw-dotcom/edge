"""Conviction→size blend (24 Jul audit: conviction was anti-predictive)."""
from __future__ import annotations

from gungnir.config import Config, Secrets
from gungnir.risk.position_sizing import VolTarget, FixedFractional
from gungnir.data.models import Signal, Side
from gungnir.features.feature_store import KrakenFeatureSet


def _cfg(**risk):
    base = {"risk": {"sizer": "vol_target", **risk}}
    return Config(base, Secrets())


def _sig(conv):
    return Signal(strategy="s", symbol="X", side=Side.BUY, conviction=conv)


def _feat():
    return KrakenFeatureSet(symbol="X", last_price=100.0, ema_fast=101.0, ema_slow=99.0,
                            rsi=55.0, atr=2.0, candles=[])


def test_full_weight_scales_linearly_with_conviction():
    s = VolTarget(_cfg(conviction_sizing_weight=1.0))
    hi = s.size(_sig(0.9), _feat(), 10_000)
    lo = s.size(_sig(0.3), _feat(), 10_000)
    assert hi > lo and abs(hi / lo - 3.0) < 1e-6      # 0.9/0.3 = 3x


def test_zero_weight_is_flat_regardless_of_conviction():
    s = VolTarget(_cfg(conviction_sizing_weight=0.0, conviction_sizing_neutral=0.5))
    assert abs(s.size(_sig(0.99), _feat(), 10_000) - s.size(_sig(0.1), _feat(), 10_000)) < 1e-12


def test_partial_weight_blends():
    s = VolTarget(_cfg(conviction_sizing_weight=0.5, conviction_sizing_neutral=0.5))
    # effective = 0.5*conv + 0.5*0.5 ; conv=1.0 → 0.75, conv=0.0 → 0.25 → 3x
    assert abs(s.size(_sig(1.0), _feat(), 10_000) / s.size(_sig(0.0), _feat(), 10_000) - 3.0) < 1e-6


def test_flat_sizing_bounded_by_neutral_not_full():
    # weight 0 with neutral 0.5 must not exceed a full-conviction (1.0) trade —
    # flattening should never balloon gross exposure.
    flat = VolTarget(_cfg(conviction_sizing_weight=0.0, conviction_sizing_neutral=0.5))
    full = VolTarget(_cfg(conviction_sizing_weight=1.0))
    assert flat.size(_sig(0.5), _feat(), 10_000) <= full.size(_sig(1.0), _feat(), 10_000)


def test_default_weight_is_backward_compatible():
    s = FixedFractional(_cfg())          # no weight set → default 1.0
    assert s._conv_weight == 1.0


# ── RL gate health (drives fail-open vs fail-safe branch) ──────────────────────

def test_rl_gate_health_thresholds():
    from gungnir.core.agent import _rl_gate_healthy
    assert _rl_gate_healthy(None, False) is True          # warmup: too few decisions
    assert _rl_gate_healthy(0.30, False) is True          # normal take rate
    assert _rl_gate_healthy(0.02, False) is False         # collapsed to near all-skip
    assert _rl_gate_healthy(0.30, True) is False          # diverged
