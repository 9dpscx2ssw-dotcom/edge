"""Regression: Overview Shadow P/L must bind to the live open-P/L status field.

The dashboard was rewritten in React (src/gungnir/dashboard/react-src/); the
generated src/gungnir/dashboard/static/index.html is a minified bundle, so
this now checks the JSX source of truth instead of grepping the bundle.
"""

from pathlib import Path


def test_overview_shadow_pl_uses_live_shadow_running_value():
    root = Path(__file__).resolve().parents[1]
    src = (root / "src/gungnir/dashboard/react-src/tabs/Overview.jsx").read_text()
    assert 'const shp = s.pnl_shadow || {};' in src
    assert "signed(shp.running)" in src
    assert "cum_pnl" not in src


if __name__ == "__main__":
    test_overview_shadow_pl_uses_live_shadow_running_value()
