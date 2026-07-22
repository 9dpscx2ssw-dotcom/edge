"""Read-only broker-account reconciliation summaries for dashboard telemetry."""
from __future__ import annotations
from typing import Iterable
from ..data.models import Trade


def broker_snapshot(positions: Iterable[Trade], balance: float, equity: float) -> dict:
    """Classify broker deals without changing or adopting any broker position."""
    rows = list(positions)
    unattributed = [p for p in rows if bool((p.context or {}).get("adopted")) and not p.strategy]
    attributed = [p for p in rows if p not in unattributed]
    return {
        "broker_balance": round(float(balance), 2),
        "broker_equity": round(float(equity), 2),
        "broker_running_pl": round(float(equity) - float(balance), 2),
        "broker_position_count": len(rows),
        "attributed_position_count": len(attributed),
        "unattributed_position_count": len(unattributed),
        "unattributed_symbols": sorted({p.symbol for p in unattributed}),
        "positions": [{
            "symbol": p.symbol, "side": p.side.value, "volume": p.volume,
            "entry_price": p.entry_price, "deal_id": (p.context or {}).get("deal_id"),
            "attribution": "unattributed" if p in unattributed else "odin",
            "strategy": p.strategy or None,
        } for p in rows],
    }
