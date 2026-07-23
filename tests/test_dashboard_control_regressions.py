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
    static_path = Path(__file__).resolve().parent.parent / "src/gungnir/dashboard/static/index.html"
    page = static_path.read_text()

    assert 'id="flt-regime-enforce"' in page
    assert "regime_mode" in page and '"enforce"' in page
    assert "Strategy mode update failed" in page
