"""Regression: Overview Shadow P/L must bind to the live open-P/L status field."""

from pathlib import Path


def test_overview_shadow_pl_uses_live_shadow_running_value():
    root = Path(__file__).resolve().parents[1]
    html = (root / "src/gungnir/dashboard/static/index.html").read_text()
    assert "setPL($('ov-shadow-pl'), shp.running);" in html
    assert "setPL($('ov-shadow-pl'), shadow.length ? shadow[shadow.length-1].cum_pnl : null);" not in html


if __name__ == "__main__":
    test_overview_shadow_pl_uses_live_shadow_running_value()
