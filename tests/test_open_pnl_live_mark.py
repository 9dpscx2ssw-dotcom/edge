"""Regression: open P/L must use the live tick mark, not the closed candle."""

from types import SimpleNamespace

from gungnir.core.agent import Agent
from gungnir.data.models import Side


def test_unrealized_prefers_live_price_over_candle_close():
    agent = object.__new__(Agent)
    agent._last_view = {"GOLD": {"price": 4074.24, "live_price": 4073.44}}
    position = SimpleNamespace(
        symbol="GOLD", entry_price=4071.83, volume=0.5934, side=Side.BUY,
    )

    assert agent._unrealized(position) == 0.96


if __name__ == "__main__":
    test_unrealized_prefers_live_price_over_candle_close()
