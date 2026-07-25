#!/usr/bin/env python3
"""Backtest every registered strategy (+ consensus) against the real cached
candles in data/gungnir.db's `candles` table — the same data the live agent
persists on every fast loop (`Database.store_candles`).

For each strategy: uses its configured timeframe from config/strategies.yaml
and its configured `symbols` (or, when unscoped, every symbol that has enough
cached history at that timeframe). Runs `backtest.engine.run()` — the exact
Strategy + FeatureSet + sizing code the live agent uses — with the configured
cost model.

Filters: by default replays the EFFECTIVE runtime pre-trade filter config —
config/config.yaml's `filters:` block (the static policy baseline) overlaid
with data/control.json's `filters` overrides (the dashboard's live runtime
knobs), exactly how `Agent.__init__`/`Agent._apply_control` assemble it. As
of this run that means regime (enforce, 9 family/regime rules) and noise
(enforce, floor-only 0.4 ATR) both actually veto entries; trend/volatility/
volume/session are off. Pass --no-filters for the raw-entry-logic view.

Caveats (documented, not silently glossed over):
  - `engine.run()` does not call `Strategy.custom_brackets()` — it always uses
    the generic ATR/pct bracket. Several strategies from this session (fixed-
    points exits, band-anchored stops, trailing SAR) rely on custom_brackets
    for their true exit behavior, so their backtested P&L here understates
    their real design and should be read as "does this entry logic find
    good trades," not "this is the strategy's real edge."
  - Live-only exit hooks (`ema_cross_exit`, `trail_field`, `stoch_exhaustion_exit`,
    `rsi_exhaustion_exit`, `alligator_cross_exit`, `on_position_closed`) are
    likewise not replayed — the backtest only knows opposite-signal or ATR-
    bracket exits.
  - Consensus is approximated by grouping the currently-shadow strategies by
    timeframe and running `run_consensus` per timeframe group — the real
    aggregator runs across strategies at DIFFERENT timeframes simultaneously
    (each on its own loop cadence), which this single-timeframe replay can't
    reproduce exactly.

Usage:
    PYTHONPATH=src python scripts/backtest_all_strategies.py [--out results.json] [--no-filters]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gungnir.backtest import engine
from gungnir.backtest.costs import CostModel
from gungnir.config import Config
from gungnir.core.aggregator import SignalAggregator
from gungnir.core.filters import FilterConfig, merge_filter_overrides
from gungnir.learning.evaluator import evaluate
from gungnir.persistence.db import Database
from gungnir.strategy.registry import StrategyRegistry, _REGISTRY

MIN_BARS = 80
CANDLE_LIMIT = 1000


def available_series(db: Database) -> dict[tuple[str, str], int]:
    rows = db.conn.execute(
        "SELECT symbol, timeframe, COUNT(*) AS n FROM candles GROUP BY symbol, timeframe"
    ).fetchall()
    return {(r["symbol"], r["timeframe"]): r["n"] for r in rows}


def _pf(m) -> float | None:
    if m.n_trades == 0 or not math.isfinite(m.profit_factor):
        return None
    return round(m.profit_factor, 2)


def _row(m, extra: dict) -> dict:
    return {
        "trades": m.n_trades,
        "win_rate": round(m.win_rate * 100, 1) if m.n_trades else None,
        "pnl": round(m.total_pnl, 2),
        "profit_factor": _pf(m),
        **extra,
    }


def build_effective_filters(cfg: Config, control_path: str = "data/control.json") -> FilterConfig:
    base = dict(cfg.get("filters", default={}) or {})
    ctrl_filters = {}
    p = Path(control_path)
    if p.exists():
        ctrl_filters = (json.loads(p.read_text()) or {}).get("filters") or {}
    return FilterConfig.from_dict(merge_filter_overrides(base, ctrl_filters))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/backtest_all_strategies.json")
    ap.add_argument("--db", default="data/gungnir.db")
    ap.add_argument("--no-filters", action="store_true",
                    help="Skip replaying the effective runtime filters (raw entry-logic view).")
    args = ap.parse_args()

    cfg = Config.load("config/config.yaml" if Path("config/config.yaml").exists()
                      else "config/config.example.yaml")
    cost = CostModel.from_config(cfg)
    bt_filters = None if args.no_filters else build_effective_filters(cfg)
    if bt_filters is not None:
        print(f"Effective filters: regime={bt_filters.regime}/{bt_filters.regime_mode} "
              f"({len(bt_filters.regime_rules)} rules), noise={bt_filters.noise}/{bt_filters.noise_mode} "
              f"(floor={bt_filters.noise_min_ema_atr}, ceiling={bt_filters.noise_max_ema_atr or 'off'}), "
              f"trend={bt_filters.trend}, volatility={bt_filters.volatility}, "
              f"volume={bt_filters.volume}, session={bt_filters.session}, spread={bt_filters.spread}\n")

    db = Database(args.db)
    avail = available_series(db)
    all_symbols = sorted({s for s, _tf in avail})

    entries = StrategyRegistry.from_yaml("config/strategies.yaml").all()
    entries_by_name = {e.name: e for e in entries}

    feats_cache: dict[tuple[str, str], tuple[list, list]] = {}

    def get_candles_and_feats(symbol: str, timeframe: str):
        key = (symbol, timeframe)
        if key not in feats_cache:
            candles = db.load_candles(symbol, timeframe, limit=CANDLE_LIMIT)
            feats = engine.feature_store.build_kraken_series(symbol, candles) if candles else []
            feats_cache[key] = (candles, feats)
        return feats_cache[key]

    results: dict[str, dict] = {}
    for name, cls in _REGISTRY.items():
        entry = entries_by_name.get(name)
        timeframe = entry.timeframe if entry else getattr(cls, "timeframe", "1h")
        configured_symbols = entry.symbols if (entry and entry.symbols) else []
        candidate_symbols = configured_symbols or all_symbols
        candidate_symbols = [s for s in candidate_symbols
                              if avail.get((s, timeframe), 0) >= MIN_BARS]
        if not candidate_symbols:
            results[name] = {"timeframe": timeframe, "symbols_tested": [],
                             "note": "no cached candles at this timeframe/symbol scope",
                             "trades": 0, "win_rate": None, "pnl": 0.0, "profit_factor": None,
                             "filter_vetoes": 0}
            continue

        per_symbol = {}
        all_trades = []
        total_vetoes = 0
        for symbol in candidate_symbols:
            candles, feats = get_candles_and_feats(symbol, timeframe)
            if not candles:
                continue
            strat = cls(params=(entry.params if entry else {}), mode="shadow", symbols=[symbol],
                       timeframe=timeframe)
            res = engine.run(strat, candles, symbol, feats=feats, cost=cost, filters=bt_filters)
            m = res.metrics
            per_symbol[symbol] = _row(m, {"bars": len(candles), "filter_vetoes": res.filter_vetoes})
            all_trades.extend(res.trades)
            total_vetoes += res.filter_vetoes

        pooled = evaluate(all_trades)
        extra = {
            "timeframe": timeframe,
            "symbols_tested": candidate_symbols,
            "filter_vetoes": total_vetoes,
            "per_symbol": per_symbol,
        }
        confirm_tf = getattr(cls, "confirm_timeframe", "")
        if confirm_tf and pooled.n_trades == 0:
            extra["note"] = (f"gates entry on a confirm_timeframe={confirm_tf!r} fetch that "
                             f"engine.run() doesn't replay (no cross-timeframe support in the "
                             f"generic backtest loop) — this 0 reflects that gap, not a real "
                             f"absence of setups")
        results[name] = _row(pooled, extra)

    # ── Consensus: group currently-shadow strategies by timeframe ──────────
    shadow_entries = [e for e in entries if e.mode == "shadow" and e.name in _REGISTRY]
    by_tf: dict[str, list] = {}
    for e in shadow_entries:
        by_tf.setdefault(e.timeframe, []).append(e)

    consensus_results = {}
    for timeframe, group in by_tf.items():
        if len(group) < 2:
            continue
        tf_symbols = [s for s in all_symbols if avail.get((s, timeframe), 0) >= MIN_BARS]
        per_symbol = {}
        all_trades = []
        total_vetoes = 0
        for symbol in tf_symbols:
            candles, feats = get_candles_and_feats(symbol, timeframe)
            if not candles:
                continue
            constituents = [_REGISTRY[e.name](params=e.params, mode="shadow", symbols=[symbol],
                                               timeframe=timeframe) for e in group]
            aggregator = SignalAggregator()
            res = engine.run_consensus(constituents, candles, symbol, aggregator=aggregator,
                                       feats=feats, cost=cost, filters=bt_filters)
            m = res.metrics
            per_symbol[symbol] = _row(m, {"filter_vetoes": res.filter_vetoes})
            all_trades.extend(res.trades)
            total_vetoes += res.filter_vetoes
        pooled = evaluate(all_trades)
        consensus_results[timeframe] = _row(pooled, {
            "constituents": [e.name for e in group],
            "symbols_tested": tf_symbols,
            "filter_vetoes": total_vetoes,
            "per_symbol": per_symbol,
        })

    db.close()

    out = {
        "filters_applied": (vars(bt_filters) if bt_filters is not None else None),
        "strategies": results,
        "consensus_by_timeframe": consensus_results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {args.out}")

    print(f"\n{len(results)} strategies checked.\n")
    rows = sorted(results.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
    print(f"{'strategy':<28}{'tf':<6}{'trades':>7}{'win%':>7}{'pf':>7}{'pnl':>10}{'vetoes':>8}")
    for name, r in rows:
        win = r["win_rate"] if r["win_rate"] is not None else "—"
        pf = r["profit_factor"] if r["profit_factor"] is not None else "—"
        print(f"{name:<28}{r['timeframe']:<6}{r['trades']:>7}{win:>7}{pf:>7}{r['pnl']:>10}{r['filter_vetoes']:>8}")

    if consensus_results:
        print("\nConsensus by timeframe:")
        for tf, r in consensus_results.items():
            print(f"  {tf:<6} trades={r['trades']:>4} win%={r['win_rate']} pf={r['profit_factor']} "
                  f"pnl={r['pnl']} vetoes={r['filter_vetoes']} constituents={r['constituents']}")


if __name__ == "__main__":
    main()
