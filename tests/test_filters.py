"""Pre-trade filters + broker-minimum lot enforcement."""

from __future__ import annotations

from datetime import datetime, timezone

from gungnir.config import Config, Secrets
from gungnir.core import filters
from gungnir.core.filters import FilterConfig
from gungnir.data.models import OrderBook, OrderBookLevel, Side, Signal
from gungnir.features.feature_store import KrakenFeatureSet
from gungnir.risk.portfolio import PortfolioRisk


def _feat(**over):
    base = dict(symbol="EURUSD", last_price=100.0, ema_fast=101.0, ema_slow=99.0,
                rsi=55.0, atr=1.0, bb_lower=98.0, bb_mid=100.0, bb_upper=102.0, adx=30.0)
    base.update(over)
    return KrakenFeatureSet(**base)


def _sig(side=Side.BUY):
    return Signal(strategy="trend_following", symbol="EURUSD", side=side, conviction=0.7)


def test_all_off_allows_everything():
    ok, why = filters.apply(_sig(), _feat(), "trend_following", FilterConfig(), "EURUSD")
    assert ok and why is None


def test_trend_filter_blocks_counter_trend():
    cfg = FilterConfig(trend=True)
    # EMA stack is up; a SELL is counter-trend → vetoed, a BUY passes.
    assert filters.apply(_sig(Side.SELL), _feat(), "x", cfg, "EURUSD")[1] == "trend"
    assert filters.apply(_sig(Side.BUY), _feat(), "x", cfg, "EURUSD")[0] is True


def test_volatility_filter_blocks_dead_and_extreme():
    cfg = FilterConfig(volatility=True, vol_min=0.001, vol_max=0.02)
    assert filters.apply(_sig(), _feat(atr=0.0001), "x", cfg, "EURUSD")[1] == "volatility"   # dead
    assert filters.apply(_sig(), _feat(atr=5.0), "x", cfg, "EURUSD")[1] == "volatility"       # wild
    assert filters.apply(_sig(), _feat(atr=1.0), "x", cfg, "EURUSD")[0] is True               # ok


def test_spread_filter_blocks_wide_quotes():
    from gungnir.features.orderbook import analyze
    cfg = FilterConfig(spread=True, max_spread_bps=5.0)
    obf = analyze(OrderBook(symbol="EURUSD", bids=[OrderBookLevel(price=99.95, size=1)],
                            asks=[OrderBookLevel(price=100.05, size=1)]))  # 10 bps spread
    assert filters.apply(_sig(), _feat(orderbook=obf), "x", cfg, "EURUSD")[1] == "spread"


def test_session_filter_blocks_outside_hours():
    cfg = FilterConfig(session=True)
    night = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)   # before FX window (7-21)
    day = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert filters.apply(_sig(), _feat(), "x", cfg, "EURUSD", now=night)[1] == "session"
    assert filters.apply(_sig(), _feat(), "x", cfg, "EURUSD", now=day)[0] is True


def test_regime_routes_explicit_family_rules_only_when_enforced():
    cfg = FilterConfig(regime=True, regime_mode="enforce", regime_rules=[
        {"family": "mean_reversion", "regime": "trend_high", "action": "avoid"},
        {"family": "trend", "regime": "range_high", "action": "avoid"},
    ])
    trend = _feat(adx=35.0, ema_fast=101.0, ema_slow=99.0)
    rng = _feat(adx=10.0)
    assert filters.apply(_sig(), trend, "mean_reversion", cfg, "EURUSD", regime="trend_high")[1] == "regime"
    assert filters.apply(_sig(), rng, "trend_following", cfg, "EURUSD", regime="range_high")[1] == "regime"
    assert filters.apply(_sig(), trend, "trend_following", cfg, "EURUSD", regime="trend_high")[0] is True


def test_instrument_min_rounds_sub_minimum_up():
    cfg = Config({"risk": {"max_per_asset_exposure": 10, "max_portfolio_exposure": 10}},
                 Secrets.from_env())
    r = PortfolioRisk(cfg)
    r.equity = 10_000.0
    r.day_start_equity = 10_000.0
    # Tiny sized volume that the broker would reject; min deal size = 1.0.
    # At price 1.0 the floored order (100 units of EURUSD → $100 notional, from
    # the forex min-lot table) is affordable, so it rounds up.
    order = r.vet(_sig(), raw_volume=0.0001, price=1.0, atr=0.01, instrument_min=1.0)
    assert order is not None and order.volume >= 1.0


def test_floor_never_inflates_past_margin_capacity():
    """Audit F-01: the min-lot floor must not round an order up beyond what the
    account can carry — the capped (dust) size is kept instead."""
    cfg = Config({"risk": {"max_per_asset_exposure": 10, "max_portfolio_exposure": 10}},
                 Secrets.from_env())
    r = PortfolioRisk(cfg)
    r.equity = 10_000.0
    r.day_start_equity = 10_000.0
    # Forex floor = 100 units; at price 100 that's $10,000 notional — beyond the
    # 1x-leverage margin capacity (~$9,090). Must NOT be inflated to the floor.
    order = r.vet(_sig(), raw_volume=0.0001, price=100.0, atr=1.0, instrument_min=1.0)
    assert order is None or order.volume < 1.0


def test_calendar_blocks_weekend_non_crypto_but_allows_crypto():
    sunday = datetime(2026, 7, 19, 20, 25, tzinfo=timezone.utc)
    assert filters.calendar_allows("EURUSD", sunday) is False
    assert filters.calendar_allows("DE40", sunday) is False
    assert filters.calendar_allows("BTCUSD", sunday) is True

def test_session_filter_blocks_weekend_even_inside_hour_window():
    cfg = FilterConfig(session=True)
    sunday = datetime(2026, 7, 19, 20, 25, tzinfo=timezone.utc)
    assert filters.apply(_sig(), _feat(), "x", cfg, "EURUSD", now=sunday)[1] == "session"



def test_regime_shadow_policy_records_hypothetical_veto_without_blocking():
    cfg = FilterConfig(
        regime=True,
        regime_mode="shadow",
        regime_rules=[{"family": "mean_reversion", "regime": "trend_high", "action": "avoid"}],
    )
    trend = _feat(adx=35.0, ema_fast=101.0, ema_slow=99.0)

    decision = filters.evaluate_regime("bb_rsi", trend, cfg, regime="trend_high")

    assert decision.family == "mean_reversion"
    assert decision.would_veto is True
    assert decision.mode == "shadow"
    assert filters.apply(_sig(), trend, "bb_rsi", cfg, "EURUSD", regime="trend_high") == (True, None)


def test_regime_policy_never_classifies_unknown_strategy_as_trend():
    cfg = FilterConfig(
        regime=True,
        regime_mode="enforce",
        regime_rules=[{"family": "trend", "regime": "range_high", "action": "avoid"}],
    )
    rng = _feat(adx=10.0)

    decision = filters.evaluate_regime("unregistered_strategy", rng, cfg, regime="range_high")

    assert decision.family == "unknown"
    assert decision.would_veto is False
    assert filters.apply(_sig(), rng, "unregistered_strategy", cfg, "EURUSD", regime="range_high") == (True, None)


def test_regime_enforcement_requires_explicit_mode_and_exact_rule():
    trend = _feat(adx=35.0, ema_fast=101.0, ema_slow=99.0)
    rules = [{"family": "mean_reversion", "regime": "trend_high", "action": "avoid"}]

    observe = FilterConfig(regime=True, regime_mode="observe", regime_rules=rules)
    enforce = FilterConfig(regime=True, regime_mode="enforce", regime_rules=rules)

    assert filters.apply(_sig(), trend, "bb_rsi", observe, "EURUSD", regime="trend_high") == (True, None)
    assert filters.apply(_sig(), trend, "bb_rsi", enforce, "EURUSD", regime="trend_high") == (False, "regime")


# ── No-trend-structure (noise) filter ─────────────────────────────────────────

def test_evaluate_noise_flags_flat_ema_as_would_block():
    # spread |101-99| = 2.0 over atr 1.0 = 2.0 ATRs → well above 0.4, no block.
    cfg = FilterConfig(noise=True, noise_min_ema_atr=0.4)
    would, ext = filters.evaluate_noise(_feat(ema_fast=101.0, ema_slow=99.0, atr=1.0), cfg)
    assert would is False and ext == 2.0
    # spread 0.2 over atr 1.0 = 0.2 ATRs → below 0.4, would block (chop).
    would, ext = filters.evaluate_noise(_feat(ema_fast=100.1, ema_slow=99.9, atr=1.0), cfg)
    assert would is True and ext == 0.2


def test_evaluate_noise_thin_features_never_block():
    cfg = FilterConfig(noise=True)
    assert filters.evaluate_noise(_feat(atr=0.0), cfg) == (False, None)


def test_noise_observe_mode_tags_but_does_not_block():
    # Chop entry (0.2 ATR spread) that WOULD block, but observe mode never vetoes.
    cfg = FilterConfig(noise=True, noise_mode="observe", noise_min_ema_atr=0.4)
    feat = _feat(ema_fast=100.1, ema_slow=99.9, atr=1.0)
    assert filters.evaluate_noise(feat, cfg)[0] is True          # would block
    assert filters.apply(_sig(), feat, "x", cfg, "EURUSD") == (True, None)  # but doesn't


def test_noise_enforce_mode_blocks_chop_entry():
    cfg = FilterConfig(noise=True, noise_mode="enforce", noise_min_ema_atr=0.4)
    chop = _feat(ema_fast=100.1, ema_slow=99.9, atr=1.0)     # 0.2 ATR spread
    trend = _feat(ema_fast=101.0, ema_slow=99.0, atr=1.0)    # 2.0 ATR spread
    assert filters.apply(_sig(), chop, "x", cfg, "EURUSD") == (False, "noise")
    assert filters.apply(_sig(), trend, "x", cfg, "EURUSD")[0] is True


def test_noise_off_by_default_is_inert():
    would, _ = filters.evaluate_noise(_feat(ema_fast=100.1, ema_slow=99.9, atr=1.0),
                                      FilterConfig())  # noise defaults off
    assert would is True  # signal still computes...
    assert filters.apply(_sig(), _feat(ema_fast=100.1, ema_slow=99.9, atr=1.0),
                         "x", FilterConfig(), "EURUSD") == (True, None)  # ...but off ⇒ no veto


def test_noise_mode_from_dict_validates():
    assert FilterConfig.from_dict({"noise_mode": "bogus"}).noise_mode == "observe"
    assert FilterConfig.from_dict({"noise": True, "noise_mode": "enforce",
                                   "noise_min_ema_atr": 0.6}).noise_min_ema_atr == 0.6


def test_consensus_family_is_ensemble_and_regime_avoid_vetoes():
    # CF1 relies on evaluate_regime("consensus", ...) resolving to the ensemble
    # family so a `family: ensemble ... avoid` rule actually gates the consensus
    # book. (The wiring into _consensus_step is verified separately.)
    assert filters.strategy_family("consensus") == "ensemble"
    cfg = FilterConfig(regime=True, regime_mode="enforce", regime_rules=[
        {"family": "ensemble", "regime": "range_high", "action": "avoid"},
    ])
    d = filters.evaluate_regime("consensus", _feat(), cfg, regime="range_high")
    assert d.would_veto and d.family == "ensemble"
    # a non-avoided regime for the same family passes
    assert filters.evaluate_regime("consensus", _feat(), cfg, regime="trend_high").would_veto is False
