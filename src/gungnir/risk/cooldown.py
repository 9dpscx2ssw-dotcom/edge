"""Loss-streak cooldown: the anti-revenge-trading guard.

In a sustained one-direction move, level-based strategies re-arm every time
their condition releases — so a mean-reversion strategy can buy a falling
market, get stopped out, and re-enter a bar later, all the way down (this is
exactly the loop a 16h incident log showed on the index symbols). Brackets cap
each loss; nothing capped the *sequence*.

This guard tracks consecutive losing round-trips per (strategy, symbol). After
``max_streak`` losses in a row, that strategy is benched on that symbol for
``cooldown_minutes``. Any winning close resets the streak (and lifts an active
bench — the market stopped disagreeing). Scoped per strategy+symbol so one
strategy's bad day doesn't bench the others.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class LossStreakGuard:
    def __init__(self, max_streak: int = 3, cooldown_minutes: float = 60.0):
        self.max_streak = int(max_streak or 0)
        self.cooldown_seconds = float(cooldown_minutes or 0.0) * 60.0
        self._streak: dict[tuple[str, str], int] = {}
        self._last_loss: dict[tuple[str, str], float] = {}

    @property
    def enabled(self) -> bool:
        return self.max_streak > 0 and self.cooldown_seconds > 0

    def record(self, strategy: str, symbol: str, pnl: float,
               now: float | None = None) -> None:
        """Feed every closed round-trip's PnL (wins reset, losses accumulate)."""
        if not self.enabled or not strategy or not symbol:
            return
        key = (strategy, symbol)
        if pnl < 0:
            streak = self._streak.get(key, 0) + 1
            self._streak[key] = streak
            self._last_loss[key] = time.monotonic() if now is None else now
            if streak == self.max_streak:
                log.warning(
                    "%s has lost %d in a row on %s — benched for %.0f minutes.",
                    strategy, streak, symbol, self.cooldown_seconds / 60.0)
        else:
            self._streak.pop(key, None)
            self._last_loss.pop(key, None)

    def blocked_seconds(self, strategy: str, symbol: str,
                        now: float | None = None) -> float:
        """Seconds of bench time remaining for this strategy on this symbol
        (0 when clear to trade)."""
        if not self.enabled:
            return 0.0
        key = (strategy, symbol)
        if self._streak.get(key, 0) < self.max_streak:
            return 0.0
        now = time.monotonic() if now is None else now
        remaining = self.cooldown_seconds - (now - self._last_loss.get(key, 0.0))
        if remaining <= 0:
            # Cooldown served: allow ONE re-entry — a further loss re-benches
            # immediately (streak stays above threshold), a win clears it.
            self._streak[key] = self.max_streak - 1
            return 0.0
        return remaining


class ReentryCooldown:
    """Unconditional per-strategy re-entry spacing (churn brake).

    Distinct from ``LossStreakGuard``, which benches only after ``max_streak``
    *losses*: this blocks ANY re-open on a (strategy, symbol) for ``bars`` bars
    of that strategy's own timeframe after its last *close*, win or lose. It
    targets the residual churn the edge-triggered emitter can't catch — a level
    signal that releases for a bar and immediately re-fires into the same tape.
    The 23–24 Jul runtime counterfactual showed those quick re-entries close at
    ~7% win, so spacing them out removed loss with negligible give-up. ``bars``
    = 0 disables it (default), so it must be opted into per config.
    """

    def __init__(self, bars: int = 0):
        self.bars = int(bars or 0)
        self._last_close: dict[tuple[str, str], float] = {}

    @property
    def enabled(self) -> bool:
        return self.bars > 0

    def record_close(self, strategy: str, symbol: str,
                     now: float | None = None) -> None:
        """Stamp the close time for a (strategy, symbol) round-trip."""
        if not self.enabled or not strategy or not symbol:
            return
        self._last_close[(strategy, symbol)] = time.monotonic() if now is None else now

    def blocked_seconds(self, strategy: str, symbol: str, bar_seconds: float,
                        now: float | None = None) -> float:
        """Seconds until this strategy may re-open on this symbol (0 = clear).

        ``bar_seconds`` is the strategy timeframe's minutes×60; a strategy with
        no prior close (or a non-positive bar length) is never blocked.
        """
        if not self.enabled or bar_seconds <= 0:
            return 0.0
        last = self._last_close.get((strategy, symbol))
        if last is None:
            return 0.0
        now = time.monotonic() if now is None else now
        remaining = self.bars * float(bar_seconds) - (now - last)
        return remaining if remaining > 0 else 0.0
