"""Strategy interface.

A Strategy is a pure function of (FeatureSet) -> list[Signal], parameterized by a
mutable `params` dict that the learning layer may update over time. Keeping
strategies deterministic and side-effect-free makes them testable and lets the
optimizer backtest parameter changes against the journal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..data.models import Side, Signal
from ..features.feature_store import FeatureSet


class Strategy(ABC):
    name: str = "base"

    # Correlation family for consensus voting (core/aggregator.py): strategies
    # sharing an indicator mechanism vote as one capped bloc, so clone count
    # can't manufacture consensus. Empty ⇒ the strategy is its own family.
    family: str = ""

    # Runtime mode, toggled from the dashboard:
    #   off    — strategy is dormant, emits no signals
    #   shadow — emits signals and "paper" trades them, but never touches the
    #            real account (use this to vet a strategy before going live)
    #   live   — trades the real account (only when not in global dry-run)
    MODES = ("off", "shadow", "live")

    # Tunable-parameter contract. DEFAULTS holds every parameter this strategy
    # reads (via ``p()``) with its out-of-the-box value; BOUNDS holds the
    # optimizer's (min, max) search range per parameter. A strategy with empty
    # BOUNDS is invisible to the Bayesian/walk-forward tuning loop.
    DEFAULTS: dict[str, float] = {}
    BOUNDS: dict[str, tuple[float, float]] = {}

    # Optional higher-timeframe confluence: a strategy that sets this to a
    # timeframe string (e.g. "5m") gets that timeframe's FeatureSet fetched
    # alongside its own and attached to `_confirm_features` before each
    # `generate()` call (Agent._decide_symbol). Empty ⇒ no extra fetch, no
    # side channel — inert for every strategy that doesn't opt in.
    confirm_timeframe: str = ""

    # Optional strategy-specific trailing exit: a strategy that sets this to a
    # nonzero EMA period (e.g. 50) has its stop ratcheted to that EMA's current
    # value each cycle (never widened) once the position is open — see
    # Agent._manage_exits. 0 ⇒ the generic ATR/breakeven trailing rules apply
    # instead.
    trail_ema_period: int = 0

    # Optional strategy-specific exit signal: a strategy that sets this True
    # has its position closed outright the moment two FeatureSet fields cross
    # back against the position's side (see Agent._manage_exits). Which
    # fields is configurable via `ema_cross_exit_fast`/`ema_cross_exit_slow`
    # (default "ema10"/"ema21" — the original hardcoded pair); any two
    # numeric FeatureSet attribute names work (e.g. "sma13"/"sma26" for
    # triple_sma). False ⇒ no effect — positions close only on stop/take-
    # profit like everything else.
    ema_cross_exit: bool = False
    ema_cross_exit_fast: str = "ema10"
    ema_cross_exit_slow: str = "ema21"

    # Optional strategy-specific exit signal: a strategy that sets this True
    # has its position closed outright once ITS OWN oscillator-exhaustion
    # condition is met (thresholds read via the strategy's own params — see
    # Agent._manage_exits). False ⇒ no effect.
    stoch_exhaustion_exit: bool = False

    # Optional strategy-specific trailing exit: a strategy that sets this to
    # a FeatureSet attribute name (e.g. "sma144") has its stop ratcheted to
    # that field's current value each cycle (offset by `trail_buffer_points`
    # FX points, never widened) — see Agent._manage_exits. Distinct from
    # `trail_ema_period` above, which looks up `ema{N}` by period rather than
    # an arbitrary named field. "" ⇒ inert.
    trail_field: str = ""

    # Optional strategy-specific exit signal: a strategy that sets this True
    # has its position closed outright the moment the Alligator lips cross
    # back through the teeth against the position's side (see
    # Agent._manage_exits). False ⇒ no effect.
    alligator_cross_exit: bool = False

    # Optional strategy-specific exit signal, same shape as
    # `stoch_exhaustion_exit` but reading the shared RSI(14) field instead of
    # stochastic %K (e.g. momentum_forex: "close longs when RSI enters the
    # overbought zone"). Thresholds read via `rsi_exit_upper`/`rsi_exit_lower`
    # params. False ⇒ no effect.
    rsi_exhaustion_exit: bool = False

    def __init__(
        self,
        params: dict | None = None,
        symbols: list[str] | None = None,
        mode: str = "shadow",
        timeframe: str = "5m",
        excluded_symbols: list[str] | None = None,
    ):
        self.params = params or {}
        self.symbols = symbols or []
        # Learned per-symbol blacklist: symbols this strategy has demonstrably
        # lost on (pruned by the slow loop). Overrides the opt-in scope above.
        self.excluded_symbols = excluded_symbols or []
        self.mode = mode if mode in self.MODES else "shadow"
        self.timeframe = timeframe
        # Populated each cycle by the agent when `confirm_timeframe` is set;
        # `None` for every strategy that hasn't opted in (see class docstring).
        self._confirm_features = None

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @abstractmethod
    def generate(self, features: FeatureSet) -> list[Signal]:
        """Emit zero or more trade intents for this asset."""

    def p(self, key: str) -> float:
        """Read a tunable parameter, falling back to the class default."""
        try:
            return float(self.params.get(key, self.DEFAULTS.get(key, 0.0)))
        except (TypeError, ValueError):
            return float(self.DEFAULTS.get(key, 0.0))

    def update_params(self, updates: dict) -> None:
        """Apply (already-gated) parameter changes from the learning layer."""
        self.params.update(updates)

    def get_parameter_bounds(self) -> dict:
        """Optimization bounds {param: (min, max)} for tunable parameters."""
        return dict(self.BOUNDS)

    def trades_symbol(self, symbol: str) -> bool:
        if symbol in self.excluded_symbols:
            return False
        return not self.symbols or symbol in self.symbols

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        """Optional stop/take-profit override for a strategy whose source
        design doesn't use the generic ATR bracket (e.g. a fixed-points stop
        or a pivot-level target). Called once per opened order, right after
        the generic `PortfolioRisk.vet()` bracket is computed.

        Return ``(stop, tp)`` — either may be ``None`` to keep the generic
        ATR-based value for that leg — or ``None`` (the default) to leave
        both legs exactly as the generic bracket set them.
        """
        return None

    def on_position_closed(self, symbol: str, side: Side, reason: str) -> None:
        """Optional notification hook: called from Agent._manage_exits right
        before a stop/take-profit-triggered close for THIS strategy's own
        position, with the reason ("stop-loss" / "breakeven-stop" /
        "take-profit"). Default no-op; a strategy whose source design reacts
        to its own exits (e.g. "after a stop-loss, don't re-open in that
        direction until the opposite signal") overrides this to track that
        state itself — see SpeculativeZigzagRSIStrategy.
        """
