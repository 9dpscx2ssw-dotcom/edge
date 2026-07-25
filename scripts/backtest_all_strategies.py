#!/usr/bin/env python3
"""Backtest every registered strategy (+ consensus) against the real cached
candles in data/gungnir.db's `candles` table — the same data the live agent
persists on every fast loop (`Database.store_candles`).

For each strategy: uses its configured timeframe from config/strategies.yaml
and its configured `symbols` (or, when unscoped, every symbol that has enough
cached history at that timeframe). Runs `backtest.engine.run()` — the exact
Strategy + FeatureSet + sizing code the live agent uses — with the configured
cost model, no live sizer/filters (raw strategy edge, not the account-level
policy overlay).

Caveats (documented, not silently glossed over):
  - `engine.run()` does not call `Strategy.custom_brackets()` — it always uses
    the generic ATR/pct bracket. Several strategies from this session (fixed-
    points exits, band-anchored stops, trailing SAR) rely on custom_brackets
    for their true exit behavior, so their backtested P&L here understates
    their real design and should be read as "does this entry logic find
    trades," not "this is the strategy's real edge."
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
    PYTHONPATH=src python scripts/backtest_all_strategies.py [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gungnir.backtest import engine
from gungnir.backtest.costs import CostModel
from gungnir.config import Config
from gungnir.core.aggregator import SignalAggregator
from gungnir.persistence.db import Database
from gungnir.strategy.registry import StrategyRegistry, _REGISTRY

MIN_BARS = 80
CANDLE_LIMIT = 1000


def available_series(db: Database) -> dict[tuple[str, str], int]:
    rows = db.conn.execute(
        "SELECT symbol, timeframe, COUNT(*) AS n FROM candles GROUP BY symbol, timeframe"
    ).fetchall()
    return {(r["symbol"], r["timeframe"]): r["n"] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/backtest_all_strategies.json")
    ap.add_argument("--db", default="data/gungnir.db")
    args = ap.parse_args()

    cfg = Config.load("config/config.yaml" if Path("config/config.yaml").exists()
                      else "config/config.example.yaml")
    cost = CostModel.from_config(cfg)
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
                             "note": "no cached candles at this timeframe/symbol scope"}
            continue

        per_symbol = {}
        agg_trades = agg_pnl = 0
        agg_wins = 0
        for symbol in candidate_symbols:
            candles, feats = get_candles_and_feats(symbol, timeframe)
            if not candles:
                continue
            strat = cls(params=(entry.params if entry else {}), mode="shadow", symbols=[symbol],
                       timeframe=timeframe)
            res = engine.run(strat, candles, symbol, feats=feats, cost=cost)
            m = res.metrics
            per_symbol[symbol] = {
                "bars": len(candles), "trades": m.n_trades,
                "win_rate": round(m.win_rate * 100, 1) if m.n_trades else None,
                "pnl": round(m.total_pnl, 2),
                "profit_factor": round(m.profit_factor, 2) if m.profit_factor == m.profit_factor
                                  and m.profit_factor not in (float("inf"), float("-inf")) else None,
            }
            agg_trades += m.n_trades
            agg_pnl += m.total_pnl
            agg_wins += round(m.win_rate * m.n_trades)

        results[name] = {
            "timeframe": timeframe,
            "symbols_tested": candidate_symbols,
            "total_trades": agg_trades,
            "win_rate": round(agg_wins / agg_trades * 100, 1) if agg_trades else None,
            "total_pnl": round(agg_pnl, 2),
            "per_symbol": per_symbol,
        }

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
        agg_trades = agg_pnl = agg_wins = 0
        for symbol in tf_symbols:
            candles, feats = get_candles_and_feats(symbol, timeframe)
            if not candles:
                continue
            constituents = [_REGISTRY[e.name](params=e.params, mode="shadow", symbols=[symbol],
                                               timeframe=timeframe) for e in group]
            aggregator = SignalAggregator()
            res = engine.run_consensus(constituents, candles, symbol, aggregator=aggregator,
                                       feats=feats, cost=cost)
            m = res.metrics
            per_symbol[symbol] = {"trades": m.n_trades,
                                  "win_rate": round(m.win_rate * 100, 1) if m.n_trades else None,
                                  "pnl": round(m.total_pnl, 2)}
            agg_trades += m.n_trades
            agg_pnl += m.total_pnl
            agg_wins += round(m.win_rate * m.n_trades)
        consensus_results[timeframe] = {
            "constituents": [e.name for e in group],
            "symbols_tested": tf_symbols,
            "total_trades": agg_trades,
            "win_rate": round(agg_wins / agg_trades * 100, 1) if agg_trades else None,
            "total_pnl": round(agg_pnl, 2),
            "per_symbol": per_symbol,
        }

    db.close()

    out = {"strategies": results, "consensus_by_timeframe": consensus_results}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")

    traded = {k: v for k, v in results.items() if v.get("total_trades")}
    print(f"\n{len(results)} strategies checked, {len(traded)} produced at least one trade.\n")
    rows = sorted(traded.items(), key=lambda kv: kv[1]["total_pnl"], reverse=True)
    print(f"{'strategy':<28}{'tf':<6}{'trades':>7}{'win%':>7}{'pnl':>10}")
    for name, r in rows:
        print(f"{name:<28}{r['timeframe']:<6}{r['total_trades']:>7}{r['win_rate']:>7}{r['total_pnl']:>10}")

    if consensus_results:
        print("\nConsensus by timeframe:")
        for tf, r in consensus_results.items():
            print(f"  {tf:<6} trades={r['total_trades']:>4} win%={r['win_rate']} pnl={r['total_pnl']} "
                  f"constituents={r['constituents']}")


if __name__ == "__main__":
    main()
