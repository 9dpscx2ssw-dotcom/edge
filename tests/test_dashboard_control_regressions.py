"""Regression contracts for dashboard control-plane behavior."""
from pathlib import Path


def test_partial_runtime_filter_override_keeps_configured_regime_policy():
    from gungnir.core.filters import merge_filter_overrides

    base = {
        "regime": True,
        "regime_mode": "shadow",
        "regime_policy_version": "shadow-regime-v1",
        "regime_rules": [
            {"family": "mean_reversion", "regime": "trend_high", "action": "avoid"},
        ],
    }
    merged = merge_filter_overrides(base, {"regime": True, "adx_trend": 30.0})

    assert merged["regime_mode"] == "shadow"
    assert merged["regime_policy_version"] == "shadow-regime-v1"
    assert merged["regime_rules"] == base["regime_rules"]
    assert merged["adx_trend"] == 30.0


def test_dashboard_exposes_enforce_regime_veto_control_and_surfaces_strategy_errors():
    """The dashboard was rewritten in React (src/gungnir/dashboard/react-src/);
    the generated static/index.html is a minified bundle, so this checks the
    JSX source of truth instead of grepping the bundle."""
    root = Path(__file__).resolve().parent.parent
    settings_src = (root / "src/gungnir/dashboard/react-src/tabs/Settings.jsx").read_text()
    strategies_src = (root / "src/gungnir/dashboard/react-src/tabs/Strategies.jsx").read_text()

    assert "Enforce regime veto" in settings_src
    assert 'body.regime_mode = filters.regimeEnforce ? "enforce" : "shadow";' in settings_src
    assert "Strategy mode update failed" in strategies_src
