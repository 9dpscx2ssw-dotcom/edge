"""A compact event-driven backtester.

Replays a candle series bar-by-bar through a strategy, sizing each signal, holding
one position per symbol at a time, and exiting on opposite signal or ATR bracket.
It reuses the live `FeatureSet` + `Strategy` + `PositionSizer` code so a backtest
exercises the *same* logic the live agent runs — no separate, drifting model.

Data: pass real candles when the cTrader feed is wired; until then
`synthetic_candles` generates a GBM-ish random walk so the feature is runnable
and demoable today.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..data.models import Candle, Side, Signal, Trade
from ..features import feature_store
from ..learning.evaluator import Metrics, evaluate
from ..strategy.base import Strategy

if TYPE_CHECKING:
    from .costs import CostModel


@dataclass
class BacktestResult:
    metrics: Metrics
    trades: list[Trade]
    equity_curve: list[dict] = field(default_factory=list)
    filter_vetoes: int = 0        # signals the live pre-trade filters vetoed
    consensus_actions: dict[str, int] = field(default_factory=dict)


def synthetic_candles(
    symbol: str,
    n: int = 500,
    start: float = 1.10,
    vol: float = 0.0015,
    seed: int | None = None,
) -> list[Candle]:
    """Generate a reproducible random-walk candle series for demos/tests."""
    rng = random.Random(seed)
    price = start
    out: list[Candle] = []
    for _ in range(n):
        drift = rng.gauss(0, vol)
        o = price
        c = max(1e-6, price + drift)
        hi = max(o, c) + abs(rng.gauss(0, vol / 2))
        lo = min(o, c) - abs(rng.gauss(0, vol / 2))
        out.append(Candle(symbol=symbol, timeframe="bt", open=o, high=hi, low=lo, close=c))
        price = c
    return out


def run(
    strategy: Strategy,
    candles: list[Candle],
    symbol: str,
    sizer=None,
    starting_equity: float = 10_000.0,
    warmup: int = 60,
    stop_atr_mult: float = 2.0,
    tp_atr_mult: float = 3.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    min_lot: float = 0.0,
    max_lot: float | None = None,
    feats: list | None = None,
    cost: "CostModel | None" = None,
    filters=None,
) -> BacktestResult:
    """Walk the series, trading one position at a time. Returns metrics + curve.

    Every strategy is fed a full ``KrakenFeatureSet`` so the 26 Kraken strategies
    (which require their extended indicators) actually emit signals — the two
    example strategies read only the base fields, which the superset still
    provides. ``sl_pct`` / ``tp_pct`` (percent of entry) override the ATR brackets
    when supplied, and ``min_lot`` / ``max_lot`` clamp the sized volume.

    ``filters`` (a ``core.filters.FilterConfig``) replays the live pre-trade veto
    gates on each entry so the backtest reflects the configured selectivity, not
    a raw one-strategy sandbox. The spread veto is inert here (no live orderbook);
    the session veto uses each bar's own timestamp.
    """
    from .costs import CostModel
    cost = cost or CostModel()      # zero-cost unless a model is supplied

    equity = starting_equity
    position: Trade | None = None
    trades: list[Trade] = []
    curve: list[dict] = []
    filter_vetoes = 0
    if filters is not None:
        from ..core.filters import apply as _apply_filters

    # Precompute every indicator once over the whole series, then index per bar —
    # so all 26 Kraken strategies (which need their extended indicators) run fast.
    # Callers backtesting many strategies on the same candles can pass a shared
    # `feats` series to skip recomputing indicators per strategy.
    if feats is None:
        feats = feature_store.build_kraken_series(symbol, candles)

    for i in range(warmup, len(candles)):
        price = candles[i].close
        features = feats[i]

        # Exit checks for an open position.
        if position is not None:
            hit_stop = position.context.get("stop")
            hit_tp = position.context.get("tp")
            exit_now = False
            if position.side == Side.BUY:
                if hit_stop and price <= hit_stop:
                    exit_now = True
                elif hit_tp and price >= hit_tp:
                    exit_now = True
            else:
                if hit_stop and price >= hit_stop:
                    exit_now = True
                elif hit_tp and price <= hit_tp:
                    exit_now = True

            signals = strategy.generate(features)
            opposite = any(s.side != position.side and s.side != Side.FLAT for s in signals)
            if exit_now or opposite:
                equity += _close(position, price, cost)
                trades.append(position)
                position = None

        # Entry.
        if position is None:
            for signal in strategy.generate(features):
                if signal.side == Side.FLAT:
                    continue
                # Pre-trade filters: replay the live veto gates (trend/volatility/
                # regime/session/volume) so the backtest matches configured
                # selectivity. Use the bar's own timestamp for the session gate.
                if filters is not None:
                    _ok, _why = _apply_filters(
                        signal, features, strategy.name, filters, symbol,
                        now=getattr(candles[i], "ts", None))
                    if not _ok:
                        filter_vetoes += 1
                        continue
                vol = sizer.size(signal, features, equity) if sizer else _default_size(
                    equity, features.atr, signal.conviction, stop_atr_mult
                )
                vol = _clamp_lot(vol, min_lot, max_lot)
                if vol <= 0:
                    continue
                if sl_pct is not None or tp_pct is not None:
                    stop, tp = _pct_brackets(signal.side, price, sl_pct, tp_pct)
                else:
                    stop, tp = _brackets(signal.side, price, features.atr, stop_atr_mult, tp_atr_mult)
                position = Trade(
                    symbol=symbol,
                    side=signal.side,
                    volume=vol,
                    # Adverse entry fill (cross the spread + slippage).
                    entry_price=cost.fill_price(signal.side, price, opening=True),
                    strategy=strategy.name,
                    mode="backtest",
                    context={"stop": stop, "tp": tp},
                )
                break

        curve.append({"i": i, "equity": round(equity, 2)})

    if position is not None:  # mark-to-close at the end
        equity += _close(position, candles[-1].close, cost)
        trades.append(position)

    return BacktestResult(metrics=evaluate(trades), trades=trades,
                          equity_curve=curve, filter_vetoes=filter_vetoes)



def run_consensus(
    strategies: list[Strategy],
    candles: list[Candle],
    symbol: str,
    *,
    aggregator=None,
    sizer=None,
    starting_equity: float = 10_000.0,
    warmup: int = 60,
    stop_atr_mult: float = 2.0,
    tp_atr_mult: float = 3.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    min_lot: float = 0.0,
    max_lot: float | None = None,
    feats: list | None = None,
    cost: "CostModel | None" = None,
    filters=None,
) -> BacktestResult:
    """Replay a portfolio of strategy stances through ``SignalAggregator``.

    This is deliberately separate from :func:`run`: Consensus is an account-level
    decision, not a constituent strategy. Every eligible strategy refreshes its
    level stance on each historical bar; the exact production aggregator then
    owns the one consensus position's enter/hold/exit decision.
    """
    from collections import Counter

    from .costs import CostModel
    from ..core.aggregator import SignalAggregator
    cost = cost or CostModel()
    aggregator = aggregator or SignalAggregator()
    equity = starting_equity
    position: Trade | None = None
    trades: list[Trade] = []
    curve: list[dict] = []
    actions: Counter[str] = Counter()
    filter_vetoes = 0
    if filters is not None:
        from ..core.filters import apply as _apply_filters
    if feats is None:
        feats = feature_store.build_kraken_series(symbol, candles)

    for i in range(warmup, len(candles)):
        price = candles[i].close
        features = feats[i]

        # Brackets are broker-side protection in production and therefore take
        # precedence over the next aggregate decision in the replay too.
        if position is not None:
            stop, tp = position.context.get("stop"), position.context.get("tp")
            hit_stop = ((position.side == Side.BUY and stop and price <= stop)
                        or (position.side == Side.SELL and stop and price >= stop))
            hit_tp = ((position.side == Side.BUY and tp and price >= tp)
                      or (position.side == Side.SELL and tp and price <= tp))
            if hit_stop or hit_tp:
                equity += _close(position, price, cost)
                trades.append(position)
                position = None

        # The live agent retains a strategy's stance until its condition releases.
        # Replaying the level semantics per bar avoids treating Consensus as a
        # collection of independent edge-triggered trades.
        for strategy in strategies:
            if not strategy.enabled or not strategy.trades_symbol(symbol):
                aggregator.clear_stance(symbol, strategy.name)
                continue
            signals = [signal for signal in strategy.generate(features)
                       if signal.side != Side.FLAT]
            if not signals:
                aggregator.clear_stance(symbol, strategy.name)
                continue
            signal = signals[-1]
            aggregator.set_stance(
                symbol, strategy.name, signal.side, signal.conviction,
                family=getattr(strategy, "family", "") or strategy.name,
                horizon=getattr(strategy, "timeframe", None),
            )

        decision = aggregator.decide(symbol, position.side if position else None)
        actions[decision.action] += 1
        if position is not None and decision.action == "exit":
            equity += _close(position, price, cost)
            trades.append(position)
            position = None
        elif position is None and decision.action == "enter" and decision.side is not None:
            signal = Signal(strategy="consensus", symbol=symbol, side=decision.side,
                            conviction=min(1.0, decision.strength),
                            rationale=(f"historical consensus {decision.consensus:+.3f} "
                                       f"from {decision.n_stances} stances"))
            if filters is not None:
                ok, _why = _apply_filters(signal, features, "consensus", filters, symbol,
                                          now=getattr(candles[i], "ts", None))
                if not ok:
                    filter_vetoes += 1
                    curve.append({"i": i, "equity": round(equity, 2)})
                    continue
            vol = sizer.size(signal, features, equity) if sizer else _default_size(
                equity, features.atr, signal.conviction, stop_atr_mult)
            vol = _clamp_lot(vol, min_lot, max_lot)
            if vol > 0:
                if sl_pct is not None or tp_pct is not None:
                    stop, tp = _pct_brackets(signal.side, price, sl_pct, tp_pct)
                else:
                    stop, tp = _brackets(signal.side, price, features.atr,
                                         stop_atr_mult, tp_atr_mult)
                position = Trade(
                    symbol=symbol, side=signal.side, volume=vol,
                    entry_price=cost.fill_price(signal.side, price, opening=True),
                    strategy="consensus", mode="backtest",
                    context={"stop": stop, "tp": tp,
                             "consensus": decision.consensus,
                             "opposing": decision.opposing,
                             "stances": decision.n_stances},
                )
        curve.append({"i": i, "equity": round(equity, 2)})

    if position is not None:
        equity += _close(position, candles[-1].close, cost)
        trades.append(position)
    return BacktestResult(metrics=evaluate(trades), trades=trades,
                          equity_curve=curve, filter_vetoes=filter_vetoes,
                          consensus_actions=dict(actions))

def _default_size(equity: float, atr: float, conviction: float, stop_mult: float) -> float:
    risk = equity * 0.005 * conviction
    stop_distance = stop_mult * atr
    return risk / stop_distance if stop_distance > 0 else 0.0


def _clamp_lot(vol: float, min_lot: float, max_lot: float | None) -> float:
    """Apply manual lot-size limits. A volume that falls below the floor is kept
    (rounded up to the floor) only if it was a real, positive size."""
    if vol <= 0:
        return 0.0
    if max_lot is not None and max_lot > 0:
        vol = min(vol, max_lot)
    if min_lot > 0:
        vol = max(vol, min_lot)
    return vol


def _brackets(side, price, atr, stop_mult, tp_mult):
    if atr <= 0:
        return None, None
    if side == Side.BUY:
        return price - stop_mult * atr, price + tp_mult * atr
    return price + stop_mult * atr, price - tp_mult * atr


def _pct_brackets(side, price, sl_pct, tp_pct):
    """Stop/take as a percentage of the entry price (e.g. sl_pct=1.5 → 1.5%)."""
    stop = tp = None
    if side == Side.BUY:
        if sl_pct:
            stop = price * (1 - sl_pct / 100.0)
        if tp_pct:
            tp = price * (1 + tp_pct / 100.0)
    else:
        if sl_pct:
            stop = price * (1 + sl_pct / 100.0)
        if tp_pct:
            tp = price * (1 - tp_pct / 100.0)
    return stop, tp


def _close(position: Trade, price: float, cost=None) -> float:
    from .costs import CostModel
    cost = cost or CostModel()
    direction = 1 if position.side == Side.BUY else -1
    exit_fill = cost.fill_price(position.side, price, opening=False)   # adverse exit
    gross = direction * (exit_fill - position.entry_price) * position.volume
    commission = (cost.commission(position.entry_price * position.volume)
                  + cost.commission(exit_fill * position.volume))
    pnl = gross - commission
    position.exit_price = exit_fill
    position.pnl = pnl
    return pnl
