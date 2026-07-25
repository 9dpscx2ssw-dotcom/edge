"""All 26 Kraken trading strategies.

Each strategy consumes a KrakenFeatureSet and emits zero or more Signals based
on its indicator logic. Strategies are deterministic and PARAMETERIZED: every
threshold is read through ``self.p(...)`` with the class default, and BOUNDS
declares the optimizer's search range — this is what makes the Bayesian /
walk-forward tuning loop able to act at all (previously every threshold was a
hardcoded literal and ``get_parameter_bounds()`` returned {} for all 26).

Conviction is graded where a natural strength measure exists, but never BELOW
``conviction_base`` — so at default parameters the firing behavior is exactly
the old one, while strong setups carry more weight through sizing and the RL
gate.
"""

from __future__ import annotations

from ..data.models import Signal, Side
from ..execution.fx import point_size as _fx_point_size
from ..features.feature_store import KrakenFeatureSet
from .base import Strategy


def _sig(strategy: Strategy, features: KrakenFeatureSet, side: Side,
         conviction: float, rationale: str = "") -> list[Signal]:
    return [Signal(strategy=strategy.name, symbol=features.symbol, side=side,
                   conviction=max(0.0, min(1.0, conviction)), rationale=rationale)]


def _crossed_up(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast <= prev_slow and fast > slow


def _crossed_down(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast >= prev_slow and fast < slow


def _has_directional_momentum(momentum_zero: float, direction: int) -> bool:
    """Require strict, zero-line momentum confirmation for the proposed side."""
    return momentum_zero > 0 if direction > 0 else momentum_zero < 0


def _daily_pivot(candles: list) -> tuple[float, float, float] | None:
    """Classic floor-trader pivot (P, R1, S1) from the last COMPLETED daily
    candle's H/L/C — the "Daily Pivot" the source app charts actually plot.

    Distinct from ``KrakenFeatureSet.pivot``, which is a per-*bar* artifact
    (recomputed from the immediately preceding candle on whatever timeframe
    that FeatureSet represents) and not a real daily level.
    """
    if not candles:
        return None
    c = candles[-1]
    p = (c.high + c.low + c.close) / 3
    r1 = 2 * p - c.low
    s1 = 2 * p - c.high
    return p, r1, s1


def _fractal_low(candles: list, order: int, lookback: int) -> float | None:
    """The most recent CONFIRMED local low — a bar whose low sits below the
    ``order`` bars on both sides of it (the classic Williams-fractal swing
    point) — searched over the last ``lookback`` candles.

    This is "the previous local low" the app's stop-loss rule references: an
    actual swing point, not just the lowest low over an arbitrary window (a
    rolling minimum can pick the entry bar's own low, giving a degenerate
    near-zero-room stop, or reach back to an unrelated old level).
    """
    if len(candles) < 2 * order + 1:
        return None
    window = candles[-lookback:] if len(candles) > lookback else candles
    n = len(window)
    for i in range(n - 1 - order, order - 1, -1):
        lo = window[i].low
        if (all(lo < window[i - k].low for k in range(1, order + 1))
                and all(lo < window[i + k].low for k in range(1, order + 1))):
            return lo
    return None


def _fractal_high(candles: list, order: int, lookback: int) -> float | None:
    """Mirror of `_fractal_low`: the most recent confirmed local high."""
    if len(candles) < 2 * order + 1:
        return None
    window = candles[-lookback:] if len(candles) > lookback else candles
    n = len(window)
    for i in range(n - 1 - order, order - 1, -1):
        hi = window[i].high
        if (all(hi > window[i - k].high for k in range(1, order + 1))
                and all(hi > window[i + k].high for k in range(1, order + 1))):
            return hi
    return None


class _EMA921ADXDMITrendBase(Strategy):
    """Closed-bar EMA(9,21,55) + Momentum(0) + DMI histogram + ADX(14)."""

    family = "trend"
    DEFAULTS = {"adx_threshold": 25.0, "conviction_base": 0.55}
    BOUNDS = {"adx_threshold": (20.0, 40.0), "conviction_base": (0.4, 0.75)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        values = (features.last_price, features.ema9, features.prev_ema9,
                  features.ema21, features.prev_ema21, features.ema55,
                  features.adx, features.momentum_zero, features.dmi_histogram)
        if any(not isinstance(v, (int, float)) or not __import__('math').isfinite(v) for v in values):
            return []
        bull = _crossed_up(features.prev_ema9, features.prev_ema21, features.ema9, features.ema21)
        bear = _crossed_down(features.prev_ema9, features.prev_ema21, features.ema9, features.ema21)
        adx_ok = features.adx > self.p("adx_threshold")
        base = self.p("conviction_base")
        strength = min(max((features.adx - self.p("adx_threshold")) / 25.0, 0.0), 1.0)
        conviction = base + (1.0 - base) * strength
        if bull and features.last_price > features.ema55 and _has_directional_momentum(features.momentum_zero, 1) and features.dmi_histogram > 0 and adx_ok:
            return _sig(self, features, Side.BUY, conviction,
                        "EMA9↑EMA21; close>EMA55; momentum>0; DMI-hist>0; ADX>25")
        if bear and features.last_price < features.ema55 and _has_directional_momentum(features.momentum_zero, -1) and features.dmi_histogram < 0 and adx_ok:
            return _sig(self, features, Side.SELL, conviction,
                        "EMA9↓EMA21; close<EMA55; momentum<0; DMI-hist<0; ADX>25")
        return []


class EMA921ADXDMITrendM5Strategy(_EMA921ADXDMITrendBase):
    """EMA9/21/55 + Momentum + DMI/ADX trend confirmation — M5."""
    name = "ema921_adx_dmi_m5"


class EMA921ADXDMITrendM15Strategy(_EMA921ADXDMITrendBase):
    """EMA9/21/55 + Momentum + DMI/ADX trend confirmation — M15."""
    name = "ema921_adx_dmi_m15"


class _EMA78CrossoverBase(Strategy):
    """Standalone closed-bar EMA(7,8) crossover strategy.

    A bullish crossover is this strategy's long entry/reversal signal; a bearish
    crossover is its short entry/reversal signal. It deliberately does not read
    EMA9/21/55, Momentum, ADX, or DMI fields.
    """

    family = "trend"
    DEFAULTS = {"conviction_base": 0.55}
    BOUNDS = {"conviction_base": (0.4, 0.75)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        values = (features.ema7, features.prev_ema7, features.ema8, features.prev_ema8)
        if any(not isinstance(v, (int, float)) or not __import__('math').isfinite(v) for v in values):
            return []
        if _crossed_up(features.prev_ema7, features.prev_ema8, features.ema7, features.ema8):
            return _sig(self, features, Side.BUY, self.p("conviction_base"),
                        "EMA7↑EMA8; standalone bullish crossover")
        if _crossed_down(features.prev_ema7, features.prev_ema8, features.ema7, features.ema8):
            return _sig(self, features, Side.SELL, self.p("conviction_base"),
                        "EMA7↓EMA8; standalone bearish crossover")
        return []


class EMA78CrossoverM5Strategy(_EMA78CrossoverBase):
    """Standalone EMA7/8 crossover — M5."""
    name = "ema78_crossover_m5"


class EMA78CrossoverM15Strategy(_EMA78CrossoverBase):
    """Standalone EMA7/8 crossover — M15."""
    name = "ema78_crossover_m15"


# Import compatibility for the prior internal class names. Runtime registration
# uses the corrected public strategy names above.
EMA921EMA78TrendM5Strategy = EMA78CrossoverM5Strategy
EMA921EMA78TrendM15Strategy = EMA78CrossoverM15Strategy



class CCIMACDStrategy(Strategy):
    """S1: CCI(14) + MACD(12,26,2) — M5 trend."""

    name = "cci_macd"
    family = "trend"
    DEFAULTS = {"cci_threshold": 100.0}
    BOUNDS = {"cci_threshold": (50.0, 200.0)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        thr = self.p("cci_threshold")
        cci = features.cci14
        macd = features.macd12_26
        conviction = min(abs(cci) / max(2 * thr, 1e-9), 1.0)
        if cci > thr and macd > 0:
            return _sig(self, features, Side.BUY, conviction)
        elif cci < -thr and macd < 0:
            return _sig(self, features, Side.SELL, conviction)
        return []


class _ParSARCCIBase(Strategy):
    """Shared SAR + CCI(45) + EMA trend-filter logic for the source app's
    "Scalping with Parabolic SAR + CCI" strategy, split into independent
    per-timeframe strategies (``parsar_cci_ema_m1``, ``parsar_cci_ema_m5``)
    rather than one M1-primary strategy with an M5 higher-timeframe
    confirmation fetch — an earlier version of this strategy used a
    ``confirm_timeframe`` cross-fetch (M1 primary + M5 EMA21 confluence);
    rebuilt here as two self-contained single-timeframe strategies instead.

    The app's own indicator list assigns EMA50 to M1 and EMA21 to M5 — read
    literally, each timeframe gets its own EMA reference, not "M1 signal
    confirmed by M5." Each variant below reads its own EMA period from its
    own timeframe's bars only; no cross-timeframe fetch, no confirm state.

    Entry compares the SAR *value* to the EMA line ("SAR point above/below
    the EMA's line"), not price to EMA — those aren't the same test. Exit
    trailing (stop follows the same EMA line, per "Stop Loss level should be
    placed at the EMA level") is opt-in via ``ema_trail_enabled`` — see
    Agent._manage_exits.

    Both variants are `mode: off` in strategies.yaml — `filters.timeframe`
    is enabled with `min_timeframe_minutes: 10` (config.yaml), so their
    signals are vetoed by that gate whenever enabled, same as any other
    sub-10-minute strategy. That's the repo's existing, deliberate M1/M5
    cost-floor policy, not something this rebuild works around.
    """

    family = "trend"
    ema_period: int = 50   # overridden per timeframe variant below

    DEFAULTS = {
        "cci_threshold": 100.0,
        "conviction_base": 0.5,
        "ema_trail_enabled": 1.0,     # 0 disables the EMA-line trailing stop
    }
    BOUNDS = {"cci_threshold": (50.0, 200.0), "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        thr = self.p("cci_threshold")
        base = self.p("conviction_base")
        cci = features.cci45
        conviction = base + 0.3 * min(max(abs(cci) - thr, 0.0) / max(thr, 1e-9), 1.0)
        ema = getattr(features, f"ema{self.ema_period}", 0.0)

        if features.sar > ema and cci > thr:
            return _sig(self, features, Side.BUY, conviction)
        elif features.sar < ema and cci < -thr:
            return _sig(self, features, Side.SELL, conviction)
        return []


class ParSARCCIM1Strategy(_ParSARCCIBase):
    """S2: Parabolic SAR + CCI(45) + EMA(50) — M1 (source app's M1 leg)."""
    name = "parsar_cci_ema_m1"
    ema_period = 50
    trail_ema_period = 50


class ParSARCCIM5Strategy(_ParSARCCIBase):
    """S2-M5: Parabolic SAR + CCI(45) + EMA(21) — M5 (source app's M5 leg)."""
    name = "parsar_cci_ema_m5"
    ema_period = 21
    trail_ema_period = 21


class BBMACDStrategy(Strategy):
    """S3: Bollinger Bands(20,2) + MACD(11,27,4) + SMA(2) — M15."""

    name = "bb_macd_sma"
    family = "meanrev"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        macd = features.macd_11_27
        base = self.p("conviction_base")
        # Grade by how far price sits from the mid-band, in half-band units.
        half = max(features.bb_upper - features.bb_mid, 1e-9)
        depth = min(abs(price - features.bb_mid) / half, 1.0)
        conviction = base + 0.3 * depth
        # Momentum confirmation: long above the mid-band WITH positive MACD,
        # short below it WITH negative MACD. The previous version had the MACD
        # condition inverted (buy above mid on falling momentum), which showed
        # up live as a 1.8% win rate over 228 trades (audit F-16).
        if price > features.bb_mid and macd > 0:
            return _sig(self, features, Side.BUY, conviction)
        elif price < features.bb_mid and macd < 0:
            return _sig(self, features, Side.SELL, conviction)
        return []


class BBMACDSMAppStrategy(Strategy):
    """S3-app: faithful replica of the source "BB, MACD, MA" app strategy — M15.

    Kept as a SEPARATE strategy from `bb_macd_sma` rather than restoring the
    original logic there: that strategy's MACD condition was deliberately
    inverted from this app spec after the literal version scored a 1.8% win
    rate over 228 live trades (audit F-16, see BBMACDStrategy's docstring).
    This variant exists to let the *unmodified* app rule be shadow-vetted on
    its own, without regressing the fix already proven live.

    Entry (contrarian reversal, per the app spec):
      Buy:  SMMA(2) crosses UP through the BB(20,2) mid-line while the
            MACD(11,27,4) histogram is still BELOW zero (momentum lagging).
      Sell: SMMA(2) crosses DOWN through the mid-line while the histogram is
            still ABOVE zero.

    Freshness: the crossover "confirms" the setup but the histogram condition
    may lag it by one bar (the two rarely land on the exact same close) — an
    open is allowed on the crossover bar or the bar immediately after it, not
    later. `FRESH_BARS` bars beyond the cross, the pending setup expires; it
    also expires immediately if price recrosses back over the mid-line before
    the histogram condition is met.
    """

    name = "bb_macd_sma_app"
    family = "meanrev"
    FRESH_BARS = 1   # allow entry on the cross bar (0) or the next bar (1)
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-symbol pending crossover, e.g. {"EURUSD": {"side": Side.BUY, "bars": 0}}.
        # Cleared once consumed (a signal fires), once it goes stale past
        # FRESH_BARS, or if price recrosses the mid-line before confirming.
        self._pending: dict[str, dict] = {}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        symbol = features.symbol
        base = self.p("conviction_base")

        crossed_up = _crossed_up(features.prev_smma2, features.prev_bb_mid,
                                 features.smma2, features.bb_mid)
        crossed_down = _crossed_down(features.prev_smma2, features.prev_bb_mid,
                                     features.smma2, features.bb_mid)

        pending = self._pending.get(symbol)
        if crossed_up:
            pending = {"side": Side.BUY, "bars": 0}
        elif crossed_down:
            pending = {"side": Side.SELL, "bars": 0}
        elif pending is not None:
            pending["bars"] += 1
            still_on_side = (
                (pending["side"] == Side.BUY and features.smma2 >= features.bb_mid) or
                (pending["side"] == Side.SELL and features.smma2 <= features.bb_mid))
            if pending["bars"] > self.FRESH_BARS or not still_on_side:
                pending = None   # window expired, or price recrossed — stale

        self._pending[symbol] = pending
        if pending is None:
            return []

        hist = features.macd_hist_11_27
        half = max(features.bb_upper - features.bb_mid, 1e-9)
        depth = min(abs(features.last_price - features.bb_mid) / half, 1.0)
        conviction = base + 0.3 * depth

        if pending["side"] == Side.BUY and hist < 0:
            self._pending[symbol] = None   # one trade per confirmed cross
            return _sig(self, features, Side.BUY, conviction)
        if pending["side"] == Side.SELL and hist > 0:
            self._pending[symbol] = None
            return _sig(self, features, Side.SELL, conviction)
        return []


class CCI200EMAStrategy(Strategy):
    """S4: CCI(200) + EMA(10,21,50) + Pivot Points — M5."""

    name = "cci200_ema_pivot"
    family = "trend"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        cci = features.cci200
        price = features.last_price
        conviction = self.p("conviction_base")
        if (features.ema10 > features.ema21 > features.ema50
                and cci > 0 and price > features.pivot):
            return _sig(self, features, Side.BUY, conviction)
        elif (features.ema10 < features.ema21 < features.ema50
                and cci < 0 and price < features.pivot):
            return _sig(self, features, Side.SELL, conviction)
        return []


class CCI200EMAPivotAppStrategy(Strategy):
    """Faithful replica of the source "Scalping strategy with CCI" app spec.

    `cci200_ema_pivot` (S4) diverges from this app spec in three ways it keeps
    deliberately: (1) it requires a full EMA10>EMA21>EMA50 stack where the app
    only requires EMA10 above both, (2) it adds a price-vs-pivot ENTRY filter
    the app never specifies — and the app's own example chart shows a valid
    buy entered *below* the daily pivot, which that filter would have
    blocked, and (3) its ``pivot`` field is a per-bar artifact (prior
    candle's H/L/C), not a real daily pivot. This variant restores the
    literal app rule on all three and is kept separate so the tightened
    original isn't disturbed.

    Entry:
      Buy:  200 CCI > 0 AND EMA10 > EMA21 AND EMA10 > EMA50.
      Sell: 200 CCI < 0 AND EMA10 < EMA21 AND EMA10 < EMA50.

    Exit (both opt-in via params, on by default — see Agent._manage_exits
    and Strategy.custom_brackets):
      TP at the nearest genuine daily pivot level, computed from the last
      COMPLETED daily candle's H/L/C via ``confirm_timeframe`` — not the
      per-bar ``KrakenFeatureSet.pivot`` field — OR the position closes
      outright when EMA10 and EMA21 cross back against it
      (``ema_cross_exit_enabled``).
      SL at a fixed points distance (``fixed_stop_points``; FX pairs only —
      "points" isn't a meaningful unit for indices/crypto, which fall back
      to the generic ATR stop).
    """

    name = "cci200_ema_pivot_app"
    family = "trend"
    confirm_timeframe = "1d"   # daily candles, for genuine floor-trader pivots
    DEFAULTS = {
        "conviction_base": 0.5,
        "fixed_stop_points": 15.0,        # 0 disables -> generic ATR stop
        "pivot_target_exit_enabled": 1.0,
        "ema_cross_exit_enabled": 1.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8), "fixed_stop_points": (8.0, 25.0)}

    @property
    def ema_cross_exit(self) -> bool:
        return self.p("ema_cross_exit_enabled") > 0

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        cci = features.cci200
        conviction = self.p("conviction_base")
        if (features.ema10 > features.ema21 and features.ema10 > features.ema50
                and cci > 0):
            return _sig(self, features, Side.BUY, conviction)
        elif (features.ema10 < features.ema21 and features.ema10 < features.ema50
                and cci < 0):
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        stop = tp = None
        pts = self.p("fixed_stop_points")
        if pts > 0:
            point = _fx_point_size(symbol)
            if point:
                dist = pts * point
                stop = entry_price - dist if side == Side.BUY else entry_price + dist
        if self.p("pivot_target_exit_enabled") > 0:
            confirm = getattr(self, "_confirm_features", None)
            candles = getattr(confirm, "candles", None) if confirm else None
            piv = _daily_pivot(candles) if candles else None
            if piv:
                pivot, r1, s1 = piv
                tp = (r1 if entry_price >= pivot else pivot) if side == Side.BUY \
                    else (s1 if entry_price <= pivot else pivot)
        return (stop, tp) if (stop is not None or tp is not None) else None


class EMAStochRSIStrategy(Strategy):
    """S5: EMA(5,10) + Stochastic(14,3,3) + RSI(14) — H1.

    Faithful to the source app spec ("EMA + Stochastic + RSI"). The EMA5/
    EMA10 "cross" condition is a level check (`ema5 > ema10`), but since the
    agent's edge-triggered emission fires only on the bar a side first
    appears, this is functionally identical to the app's crossover trigger —
    no separate cross-detection needed. Three legs the previous version
    dropped are restored here directly (overwritten in place, not split into
    a separate variant, since this strategy was never faithful to begin
    with):

      * Entry requires the stochastic %K AND %D lines to be sloping in the
        trade's direction ("stochastic's lines are directed up/down"), not
        just clear of the 80/20 zone (`stoch_slope_confirm_enabled`).
      * Exit closes outright on stochastic exhaustion — %K above
        `stoch_exit_upper` (70) for longs, below `stoch_exit_lower` (30) for
        shorts — instead of the generic ATR target
        (`stoch_exhaustion_exit_enabled`; see Agent._manage_exits).
      * The stop sits at the previous confirmed local low/high (a Williams-
        fractal swing point, not a rolling window minimum/maximum — see
        `_fractal_low`/`_fractal_high`) instead of a fixed ATR distance
        (`swing_stop_enabled`; see `custom_brackets`).
    """

    name = "ema_stoch_rsi"
    family = "oscillator"
    DEFAULTS = {
        "rsi_mid": 50.0, "stoch_upper": 80.0, "stoch_lower": 20.0,
        "conviction_base": 0.5,
        "stoch_slope_confirm_enabled": 1.0,
        "stoch_exit_upper": 70.0, "stoch_exit_lower": 30.0,
        "stoch_exhaustion_exit_enabled": 1.0,
        "swing_fractal_order": 2.0,   # bars required on each side to confirm a swing point
        "swing_lookback": 50.0,       # how far back to search for one
        "swing_stop_enabled": 1.0,
    }
    BOUNDS = {"rsi_mid": (40.0, 60.0), "stoch_upper": (60.0, 95.0),
              "stoch_lower": (5.0, 40.0), "conviction_base": (0.3, 0.8),
              "swing_lookback": (20.0, 100.0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entry_candles: list = []   # stashed by generate() for custom_brackets

    @property
    def stoch_exhaustion_exit(self) -> bool:
        return self.p("stoch_exhaustion_exit_enabled") > 0

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        rsi_mid = self.p("rsi_mid")
        base = self.p("conviction_base")
        rsi = features.rsi
        stoch_k = features.stoch_k
        stoch_d = features.stoch_d
        conviction = base + 0.3 * min(abs(rsi - 50.0) / 50.0, 1.0)

        slope_up = slope_down = True   # inert unless the toggle below is on
        if self.p("stoch_slope_confirm_enabled") > 0:
            slope_up = stoch_k > features.prev_stoch_k and stoch_d > features.prev_stoch_d
            slope_down = stoch_k < features.prev_stoch_k and stoch_d < features.prev_stoch_d

        if (features.ema5 > features.ema10 and rsi > rsi_mid
                and stoch_k < self.p("stoch_upper") and slope_up):
            self._entry_candles = features.candles
            return _sig(self, features, Side.BUY, conviction)
        elif (features.ema5 < features.ema10 and rsi < rsi_mid
                and stoch_k > self.p("stoch_lower") and slope_down):
            self._entry_candles = features.candles
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        # TP is left to the generic ATR bracket as a backstop — the app's
        # exit is a level trigger (stoch_exhaustion_exit), not a price
        # target, so only the stop leg is overridden here.
        if self.p("swing_stop_enabled") <= 0 or not self._entry_candles:
            return None
        order = max(1, int(self.p("swing_fractal_order")))
        lookback = max(2 * order + 1, int(self.p("swing_lookback")))
        if side == Side.BUY:
            stop = _fractal_low(self._entry_candles, order, lookback)
            return (stop, None) if stop is not None and stop < entry_price else None
        stop = _fractal_high(self._entry_candles, order, lookback)
        return (stop, None) if stop is not None and stop > entry_price else None


class CCIReversalStrategy(Strategy):
    """S6: CCI(14) Reversal — H1.

    Overwritten in place to match the source app spec ("CCI strategy") — the
    prior version wasn't faithful to begin with, so there's no earlier
    empirical rationale to protect by splitting into a variant. This one
    matters more than the others: it was running `mode: shadow` in the
    curated live pool with its entry direction literally INVERTED from the
    app, and its live-shadow track record (29% win, -31.2 pnl — one of the
    "broken archetype" strategies `patch_control_broken_archetypes.py`
    targets) is consistent with that inversion.

    App rule (a momentum-confirmation reversal, not a single-threshold
    contrarian trigger): buy when CCI is CURRENTLY in the overbought zone
    (>=150) but was in the oversold zone (<=-150) at some point before that;
    mirror for sells. The old code fired on a single threshold touch with NO
    prior-zone memory, and in the OPPOSITE direction (bought oversold,
    i.e. "buy the dip" — the app buys confirmed strength AFTER a washout,
    not the washout itself).

    `_last_extreme` is the per-symbol state: the most recent extreme zone
    touched. A signal fires only when the CURRENT zone is the opposite of
    the remembered one, which also makes it self-consuming — after firing,
    the state updates to the current zone, so a sustained overbought read
    can't refire until CCI dips to oversold again.
    """

    name = "cci_reversal"
    family = "meanrev"
    DEFAULTS = {
        "cci_threshold": 150.0,
        "conviction_base": 0.5,
        "tp_points": 17.5,      # app: 15-20 points from entry
        "sl_points": 5.0,       # app: 5 points from entry
        "fixed_exit_enabled": 1.0,
    }
    BOUNDS = {"cci_threshold": (100.0, 200.0), "conviction_base": (0.3, 0.8),
              "tp_points": (10.0, 25.0), "sl_points": (3.0, 10.0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_extreme: dict[str, str] = {}   # symbol -> "oversold" | "overbought"

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        thr = self.p("cci_threshold")
        base = self.p("conviction_base")
        cci = features.cci14
        symbol = features.symbol
        conviction = base + 0.3 * min(max(abs(cci) - thr, 0.0) / max(thr, 1e-9), 1.0)

        in_overbought = cci >= thr
        in_oversold = cci <= -thr
        prev = self._last_extreme.get(symbol)
        signal: list[Signal] = []
        if in_overbought and prev == "oversold":
            signal = _sig(self, features, Side.BUY, conviction)
        elif in_oversold and prev == "overbought":
            signal = _sig(self, features, Side.SELL, conviction)

        # Update the remembered extreme AFTER deciding — the confirmation
        # must compare against the zone touched BEFORE this bar, and this
        # also makes the state self-consuming (see class docstring).
        if in_overbought:
            self._last_extreme[symbol] = "overbought"
        elif in_oversold:
            self._last_extreme[symbol] = "oversold"
        return signal

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None   # not a recognized FX pair -> generic ATR bracket applies
        tp_dist = self.p("tp_points") * point
        sl_dist = self.p("sl_points") * point
        if side == Side.BUY:
            return entry_price - sl_dist, entry_price + tp_dist
        return entry_price + sl_dist, entry_price - tp_dist


class ADXMomentumStrategy(Strategy):
    """S7: ADX(14) + Momentum(14) + EMA(55) — M5."""

    name = "adx_momentum_ema"
    family = "trend"
    DEFAULTS = {"adx_threshold": 25.0, "momentum_mid": 100.0}
    BOUNDS = {"adx_threshold": (15.0, 40.0), "momentum_mid": (95.0, 105.0)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        adx_thr = self.p("adx_threshold")
        mom_mid = self.p("momentum_mid")
        adx = features.adx
        mom = features.momentum
        price = features.last_price
        if adx <= adx_thr:
            return []
        # Trend strength grades conviction: barely-trending 0.4 → strong 0.8.
        conviction = 0.4 + 0.4 * min((adx - adx_thr) / max(adx_thr, 1e-9), 1.0)
        if features.plus_di > features.minus_di and mom > mom_mid and price > features.ema55:
            return _sig(self, features, Side.BUY, conviction)
        elif features.plus_di < features.minus_di and mom < mom_mid and price < features.ema55:
            return _sig(self, features, Side.SELL, conviction)
        return []


class BBRSICuttingStrategy(Strategy):
    """S8: BB(20,2) + ADX(14) + RSI(7) — M5.

    Overwritten in place to match the source app "Cutting Points" — never
    faithful to begin with (mode: off, no prior track record), so no earlier
    empirical rationale to protect by keeping a separate variant. Two real
    gaps fixed:

    * RSI period: used the shared, globally-computed RSI(14) (`features.rsi`)
      instead of a genuine RSI(7) (`features.rsi7`).
    * Entry was a single-bar level check (price at the band + RSI/ADX zone,
      fires immediately). The app is a two-phase setup: price reaching the
      band with RSI/ADX confirmed only ARMS it; the actual entry fires when
      price then RETURNS back inside the band. Firing on the raw band touch
      risks entering while the move is still extending; the app's design
      waits for the bounce to actually start.

    Entry:
      Buy:  armed when price <= lower band, RSI(7) < 30, ADX(14) < 30 (all
            three, any bar); triggers on a later bar when price closes back
            above the lower band while still armed.
      Sell: mirror — armed at the upper band with RSI(7) > 70, ADX < 30;
            triggers when price closes back below the upper band.
    Exit (custom_brackets): TP at the BB mid-line by default, or a fixed
    3-5 point "quick" target (`quick_tp_enabled`) — the app offers both, mid-
    line target is the primary/default. SL is 3 points (`sl_buffer_points`)
    beyond the band value at the moment the setup armed, FX pairs only.
    """

    name = "bb_rsi_cutting"
    family = "meanrev"
    DEFAULTS = {
        "rsi_oversold": 30.0, "rsi_overbought": 70.0, "adx_max": 30.0,
        "conviction_base": 0.5,
        "sl_buffer_points": 3.0,      # app: 3 points beyond the band
        "quick_tp_enabled": 0.0,      # 0 -> TP at BB mid (default); 1 -> fixed quick_tp_points
        "quick_tp_points": 4.0,       # app: 3-5 points
        "fixed_exit_enabled": 1.0,
    }
    BOUNDS = {"rsi_oversold": (10.0, 40.0), "rsi_overbought": (60.0, 90.0),
              "adx_max": (20.0, 50.0), "conviction_base": (0.3, 0.8)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending: dict[str, str] = {}   # symbol -> "buy" | "sell", armed
        self._entry_band: float | None = None
        self._entry_mid: float | None = None

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        rsi = features.rsi7
        adx = features.adx
        conviction = self.p("conviction_base")
        symbol = features.symbol
        adx_ok = adx < self.p("adx_max")

        pending = self._pending.get(symbol)
        if price <= features.bb_lower and rsi < self.p("rsi_oversold") and adx_ok:
            pending = "buy"
        elif price >= features.bb_upper and rsi > self.p("rsi_overbought") and adx_ok:
            pending = "sell"
        self._pending[symbol] = pending

        if pending == "buy" and price > features.bb_lower:
            self._pending[symbol] = None
            self._entry_band, self._entry_mid = features.bb_lower, features.bb_mid
            return _sig(self, features, Side.BUY, conviction)
        if pending == "sell" and price < features.bb_upper:
            self._pending[symbol] = None
            self._entry_band, self._entry_mid = features.bb_upper, features.bb_mid
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        stop = None
        if self._entry_band is not None:
            buffer_dist = self.p("sl_buffer_points") * point
            stop = (self._entry_band - buffer_dist if side == Side.BUY
                    else self._entry_band + buffer_dist)
        if self.p("quick_tp_enabled") > 0:
            tp_dist = self.p("quick_tp_points") * point
            tp = entry_price + tp_dist if side == Side.BUY else entry_price - tp_dist
        else:
            tp = self._entry_mid
        return stop, tp


class AwesomeOscillatorStrategy(Strategy):
    """S9: Awesome Oscillator + MACD(5,7,4) — H4."""

    name = "ao_macd"
    family = "oscillator"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        conviction = self.p("conviction_base")
        if features.ao > 0 and features.macd_5_7 > 0:
            return _sig(self, features, Side.BUY, conviction)
        elif features.ao < 0 and features.macd_5_7 < 0:
            return _sig(self, features, Side.SELL, conviction)
        return []


class AwesomeMACDAppStrategy(Strategy):
    """Faithful replica of the source app "Awesome and MACD" strategy — H4.

    Kept separate from `ao_macd` above, which uses a static level-agreement
    check (AO and MACD both positive/negative right now) rather than the
    app's actual rule: a zero-line CROSS on the Awesome Oscillator,
    confirmed by the MACD *histogram*'s current zone — a momentum-pullback
    entry (buy when AO's momentum is fading through zero while the MACD
    histogram is still positive from the prior move), not a simple
    same-direction alignment.

    Entry:
      Buy:  AO crosses the zero line FROM ABOVE (prev_ao >= 0, ao < 0) while
            the MACD(5,7,4) histogram is still positive.
      Sell: AO crosses the zero line FROM BELOW (prev_ao <= 0, ao > 0) while
            the histogram is still negative.
    Exit (custom_brackets, FX pairs only): TP 50-70 points from entry
    (`tp_points`, default 60 — the app gives a range, not a single value);
    SL a flat 20 points (`sl_points`).
    """

    name = "ao_macd_app"
    family = "oscillator"
    DEFAULTS = {
        "conviction_base": 0.5,
        "tp_points": 60.0,     # app: 50-70 points
        "sl_points": 20.0,
        "fixed_exit_enabled": 1.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8), "tp_points": (50.0, 70.0)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        conviction = self.p("conviction_base")
        crossed_down_thru_zero = _crossed_down(features.prev_ao, 0.0, features.ao, 0.0)
        crossed_up_thru_zero = _crossed_up(features.prev_ao, 0.0, features.ao, 0.0)
        hist = features.macd_hist_5_7

        if crossed_down_thru_zero and hist > 0:
            return _sig(self, features, Side.BUY, conviction)
        elif crossed_up_thru_zero and hist < 0:
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        tp_dist = self.p("tp_points") * point
        sl_dist = self.p("sl_points") * point
        if side == Side.BUY:
            return entry_price - sl_dist, entry_price + tp_dist
        return entry_price + sl_dist, entry_price - tp_dist


class _BBRSIBase(Strategy):
    """Source app "Bollinger Bands and RSI": BB(20,2) + RSI(11) breakout-
    continuation, shared across the app's two listed timeframes (bb_rsi/M15,
    bb_rsi_m30/M30 below) — same pattern as `_HMADonchianBase`.

    Entry was already faithful before this pass (RSI > 70 with price above
    the upper band for longs, mirror for shorts — a momentum-continuation
    rule despite the classic-looking 70/30 zones, not mean-reversion). Two
    real gaps fixed here:

    * RSI period: every strategy in this codebase previously shared one
      globally-computed RSI(14) (`features.rsi`); the app calls for RSI(11)
      specifically. `features.rsi11` is now computed alongside it.
    * Exit: the app specifies a fixed-points TP table keyed by (timeframe,
      instrument) — 15/19 pts on M15 for EURUSD/GBPUSD, 19/25 pts on M30 —
      plus a flat 10-point SL, nothing like the generic ATR bracket every
      strategy defaults to. Implemented via `custom_brackets`, scoped to
      exactly the instruments the app names; anything else (or a symbol/
      timeframe combination outside the table) falls back to the generic
      ATR bracket rather than guessing a number the app never specified.
    """

    family = "meanrev"
    DEFAULTS = {"rsi_overbought": 70.0, "rsi_oversold": 30.0, "conviction_base": 0.5,
                "sl_points": 10.0, "fixed_exit_enabled": 1.0}
    BOUNDS = {"rsi_overbought": (60.0, 90.0), "rsi_oversold": (10.0, 40.0),
              "conviction_base": (0.3, 0.8)}

    # App's fixed-points TP table: (timeframe, symbol) -> TP distance in points.
    _TP_POINTS = {
        ("15m", "EURUSD"): 15.0, ("15m", "GBPUSD"): 19.0,
        ("30m", "EURUSD"): 19.0, ("30m", "GBPUSD"): 25.0,
    }

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        rsi = features.rsi11
        conviction = self.p("conviction_base")
        if rsi > self.p("rsi_overbought") and price > features.bb_upper:
            return _sig(self, features, Side.BUY, conviction)
        elif rsi < self.p("rsi_oversold") and price < features.bb_lower:
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        tp_pts = self._TP_POINTS.get((self.timeframe, symbol))
        if tp_pts is None:
            return None   # outside the app's named table -> generic ATR bracket
        sl_dist = self.p("sl_points") * point
        tp_dist = tp_pts * point
        if side == Side.BUY:
            return entry_price - sl_dist, entry_price + tp_dist
        return entry_price + sl_dist, entry_price - tp_dist


class BBRSIStrategy(_BBRSIBase):
    """S10: Bollinger Bands(20,2) + RSI(11) — M15."""
    name = "bb_rsi"


class BBRSIM30Strategy(_BBRSIBase):
    """S10-M30: Bollinger Bands(20,2) + RSI(11) — M30 (source app's second
    listed timeframe; same rule, its own exit-table row)."""
    name = "bb_rsi_m30"


class IntelligentTradingStrategy(Strategy):
    """S11: SMMA(8,18) + ParSAR + Stoch + MACD — H1."""

    name = "intelligent_trading"
    family = "trend"
    DEFAULTS = {"stoch_mid": 50.0, "conviction_base": 0.6}
    BOUNDS = {"stoch_mid": (30.0, 70.0), "conviction_base": (0.3, 0.9)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        stoch_mid = self.p("stoch_mid")
        conviction = self.p("conviction_base")
        macd = features.macd12_26
        if (features.smma8 > features.smma18 and macd > 0
                and features.stoch_k < stoch_mid and features.sar_trend > 0):
            return _sig(self, features, Side.BUY, conviction)
        elif (features.smma8 < features.smma18 and macd < 0
                and features.stoch_k > stoch_mid and features.sar_trend < 0):
            return _sig(self, features, Side.SELL, conviction)
        return []


class MultiBBStrategy(Strategy):
    """S12: Multi-deviation BB(20; 2,3,4) — M1."""

    name = "multi_bb"
    family = "meanrev"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        base = self.p("conviction_base")
        # Deeper penetration past the band → higher conviction.
        half = max(features.bb_upper - features.bb_mid, 1e-9)
        if price <= features.bb_lower:
            depth = min((features.bb_lower - price) / half, 1.0)
            return _sig(self, features, Side.BUY, base + 0.3 * depth)
        elif price >= features.bb_upper:
            depth = min((price - features.bb_upper) / half, 1.0)
            return _sig(self, features, Side.SELL, base + 0.3 * depth)
        return []


class MultiBBAppStrategy(Strategy):
    """Faithful replica of the source app "Bollinger Bands for GBP/JPY" —
    kept separate from `multi_bb` (S12) above.

    `multi_bb` diverges from this app spec in ways worth keeping split out
    rather than reverting: it collapsed the app's three-band (dev 2/3/4)
    system down to a single dev=2 band with an UNBOUNDED entry (any
    excursion past dev2 fires, arbitrarily far — not just the dev2-to-dev3
    zone the app describes), it isn't scoped to GBP/JPY (the instrument the
    app is literally named for and point-calibrated to), and it runs on 15m
    rather than the app's M1 — the latter is a deliberate, documented
    cost-floor tradeoff (see strategies.yaml), preserved here too rather
    than reverted, since M1/M5 rarely clear retail spreads regardless of
    which variant is asking.

    Entry: price in the BOUNDED zone between the dev=2 and dev=3 lines —
    "reached the bottom line of dev2, or trading between dev2 and dev3" per
    the app text, which (2,3) inclusive resolves to bounded, not open-ended.
    dev=4 is computed (`bb4_lower`/`bb4_upper`, a named indicator in the
    app's list) but not gated on here: the app's buy/sell/exit rules never
    reference it, so no rule is invented for a boundary the source doesn't
    state one for.

    Exit: SL = 2 points beyond the nearest confirmed local low/high (reuses
    `_fractal_low`/`_fractal_high`, the swing-point detector built for
    ema_stoch_rsi); TP = a fixed 15 points from entry. Both toggleable.
    """

    name = "multi_bb_app"
    family = "meanrev"
    DEFAULTS = {
        "conviction_base": 0.5,
        "tp_points": 15.0,          # app: 15 points from the opening price
        "sl_buffer_points": 2.0,    # app: 2 points beyond the nearest local low/high
        "fixed_exit_enabled": 1.0,
        "swing_fractal_order": 2.0,
        "swing_lookback": 50.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8), "tp_points": (7.0, 20.0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entry_candles: list = []   # stashed by generate() for custom_brackets

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        base = self.p("conviction_base")
        zone = max(features.bb_lower - features.bb3_lower, 1e-9)

        if features.bb3_lower <= price <= features.bb_lower:
            depth = min((features.bb_lower - price) / zone, 1.0)
            self._entry_candles = features.candles
            return _sig(self, features, Side.BUY, base + 0.3 * depth)
        elif features.bb_upper <= price <= features.bb3_upper:
            depth = min((price - features.bb_upper) / zone, 1.0)
            self._entry_candles = features.candles
            return _sig(self, features, Side.SELL, base + 0.3 * depth)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        tp_dist = self.p("tp_points") * point
        tp = entry_price + tp_dist if side == Side.BUY else entry_price - tp_dist

        stop = None
        if self._entry_candles:
            order = max(1, int(self.p("swing_fractal_order")))
            lookback = max(2 * order + 1, int(self.p("swing_lookback")))
            buffer_dist = self.p("sl_buffer_points") * point
            if side == Side.BUY:
                swing = _fractal_low(self._entry_candles, order, lookback)
                if swing is not None:
                    stop = swing - buffer_dist
                    if stop >= entry_price:
                        stop = None
            else:
                swing = _fractal_high(self._entry_candles, order, lookback)
                if swing is not None:
                    stop = swing + buffer_dist
                    if stop <= entry_price:
                        stop = None
        return stop, tp


class MACDStochStrategy(Strategy):
    """S13: MACD(13,26,9) + Stochastic(5,3,3) — M1."""

    name = "macd_stoch"
    family = "oscillator"
    DEFAULTS = {"stoch_lower": 20.0, "stoch_upper": 80.0, "conviction_base": 0.5}
    BOUNDS = {"stoch_lower": (5.0, 40.0), "stoch_upper": (60.0, 95.0),
              "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        macd = features.macd_13_26
        stoch_k = features.stoch_k
        conviction = self.p("conviction_base")
        if macd > 0 and stoch_k < self.p("stoch_lower"):
            return _sig(self, features, Side.BUY, conviction)
        elif macd < 0 and stoch_k > self.p("stoch_upper"):
            return _sig(self, features, Side.SELL, conviction)
        return []


class AlligatorStrategy(Strategy):
    """S14: Williams Alligator(13/8/5) + SMA(144) — H1 (app recommends M15,
    "longer periods are admissible too" — H1 is within spec, not a
    cost-floor conflict like the M1/M5 cases elsewhere).

    Overwritten in place to match the source app spec ("Alligator") — never
    faithful to begin with (generic ATR bracket instead of the app's
    SMA144-tracking stop and lips/teeth reversal close), so there's no prior
    empirical rationale to protect by keeping a separate variant. This
    strategy is `mode: off` and has never traded.

    Entry: SMA144 trend filter + full lips>teeth>jaw alignment (unchanged —
    already faithful; edge-triggered by the agent's generic emission, a
    reasonable proxy for the app's "lips crossed both other lines, teeth
    crossed jaw, both from below" even though it isn't bar-for-bar the same
    two-event test).

    Exit:
      SL tracks SMA144 continuously, 1 point beyond it ("all the time" — not
      set once at entry), via the generic `trail_field`/`trail_buffer_points`
      hook (see Agent._manage_exits).
      Closes outright when the lips cross back through the teeth against the
      position (`alligator_cross_exit`), per "closed once the green line has
      crossed the red line" — not a fixed price target.
    """

    name = "alligator"
    family = "trend"
    trail_field = "sma144"
    DEFAULTS = {
        "conviction_base": 0.5,
        "trail_field_enabled": 1.0,
        "trail_buffer_points": 1.0,   # app: 1 point beyond SMA144
        "alligator_cross_exit_enabled": 1.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    @property
    def alligator_cross_exit(self) -> bool:
        return self.p("alligator_cross_exit_enabled") > 0

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        conviction = self.p("conviction_base")
        if (features.alligator_lips > features.alligator_teeth > features.alligator_jaw
                and price > features.sma144):
            return _sig(self, features, Side.BUY, conviction)
        elif (features.alligator_lips < features.alligator_teeth < features.alligator_jaw
                and price < features.sma144):
            return _sig(self, features, Side.SELL, conviction)
        return []


class _HMADonchianBase(Strategy):
    """HMA(55) + Donchian(20) trend-following, shared across six timeframes."""

    family = "channel"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        base = self.p("conviction_base")
        # Distance from the HMA in ATR units grades trend maturity.
        atr = features.atr or 0.0
        stretch = min(abs(price - features.hma55) / atr, 1.0) if atr > 0 else 0.0
        conviction = base + 0.3 * stretch
        if price > features.hma55 and features.dc_trend > 0:
            return _sig(self, features, Side.BUY, conviction)
        elif price < features.hma55 and features.dc_trend < 0:
            return _sig(self, features, Side.SELL, conviction)
        return []


class HMADonchianM1Strategy(_HMADonchianBase):
    """S15: HMA(55) + Donchian(20) — M1."""
    name = "hma_dc_m1"


class HMADonchianM5Strategy(_HMADonchianBase):
    """S16: HMA(55) + Donchian(20) — M5."""
    name = "hma_dc_m5"


class HMADonchianM15Strategy(_HMADonchianBase):
    """S17: HMA(55) + Donchian(20) — M15."""
    name = "hma_dc_m15"


class HMADonchianH1Strategy(_HMADonchianBase):
    """S18: HMA(55) + Donchian(20) — H1."""
    name = "hma_dc_h1"


class HMADonchianH4Strategy(_HMADonchianBase):
    """S19: HMA(55) + Donchian(20) — H4."""
    name = "hma_dc_h4"


class HMADonchianD1Strategy(_HMADonchianBase):
    """S20: HMA(55) + Donchian(20) — D1."""
    name = "hma_dc_d1"


class _FVGBase(Strategy):
    """Fair Value Gap retracement entries, shared across four timeframes."""

    family = "structure"
    DEFAULTS = {"conviction_base": 0.6}
    BOUNDS = {"conviction_base": (0.3, 0.9)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        conviction = self.p("conviction_base")
        if (features.fvg_bull_bot > 0
                and features.fvg_bull_bot <= price <= features.fvg_bull_top):
            return _sig(self, features, Side.BUY, conviction)
        if (features.fvg_bear_bot > 0
                and features.fvg_bear_bot <= price <= features.fvg_bear_top):
            return _sig(self, features, Side.SELL, conviction)
        return []


class FVGM1Strategy(_FVGBase):
    """S21: Fair Value Gap — M1."""
    name = "fvg_m1"


class FVGM5Strategy(_FVGBase):
    """S22: Fair Value Gap — M5."""
    name = "fvg_m5"


class FVGM15Strategy(_FVGBase):
    """S23: Fair Value Gap — M15."""
    name = "fvg_m15"


class FVGM30Strategy(_FVGBase):
    """S24: Fair Value Gap — M30."""
    name = "fvg_m30"


class _ScalpEMAVWAPBase(Strategy):
    """9-EMA × VWAP scalp, shared across two timeframes.

    ``min_gap_bps`` (default 0 = old behavior) requires the EMA to clear the
    VWAP by a minimum distance — the raw crossover fires on every bar of noise.
    """

    family = "scalp"
    DEFAULTS = {"conviction_base": 0.6, "min_gap_bps": 0.0}
    BOUNDS = {"conviction_base": (0.3, 0.9), "min_gap_bps": (0.0, 20.0)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price or 0.0
        if price <= 0 or features.vwap_val <= 0:
            return []
        gap_bps = (features.ema5 - features.vwap_val) / price * 10_000.0
        conviction = self.p("conviction_base")
        min_gap = self.p("min_gap_bps")
        if gap_bps > min_gap:
            return _sig(self, features, Side.BUY, conviction)
        elif gap_bps < -min_gap:
            return _sig(self, features, Side.SELL, conviction)
        return []


class FashionablyLateScalpM1Strategy(_ScalpEMAVWAPBase):
    """S25: Fashionably Late Scalp — 9 EMA × VWAP — M1."""
    name = "scalp_ema_vwap_m1"


class FashionablyLateScalpM5Strategy(_ScalpEMAVWAPBase):
    """S26: Fashionably Late Scalp — 9 EMA × VWAP — M5."""
    name = "scalp_ema_vwap_m5"


class _FollowTheTrendBase(Strategy):
    """Faithful replica of the source app "Follow the Trend" strategy,
    split into independent per-timeframe strategies (H4, D1 — its own exit
    table gives each a different TP) rather than one strategy with a
    timeframe-conditional bracket, same pattern as `_BBRSIBase`.

    Entry:
      Buy:  +DI(28) > -DI(28) AND 4EMA crosses 10EMA from below AND
            MACD(5,10,4) > 0.
      Sell: -DI(28) > +DI(28) AND 4EMA crosses 10EMA from above AND
            MACD(5,10,4) < 0.
    Exit (custom_brackets, FX pairs only): TP is a fixed points distance
    read from `_TP_POINTS` (keyed by timeframe: 60 on H4, 200 on D1); SL is
    exactly 1/3 of TP ("StopLoss: 3 times less than TP").
    """

    family = "trend"
    DEFAULTS = {"conviction_base": 0.5, "fixed_exit_enabled": 1.0}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

    # App's fixed-points TP table, keyed by timeframe; SL is always TP/3.
    _TP_POINTS = {"4h": 60.0, "1d": 200.0}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        conviction = self.p("conviction_base")
        crossed_up = _crossed_up(features.prev_ema4, features.prev_ema10,
                                 features.ema4, features.ema10)
        crossed_down = _crossed_down(features.prev_ema4, features.prev_ema10,
                                     features.ema4, features.ema10)

        if (features.plus_di28 > features.minus_di28 and crossed_up
                and features.macd_5_10 > 0):
            return _sig(self, features, Side.BUY, conviction)
        elif (features.minus_di28 > features.plus_di28 and crossed_down
                and features.macd_5_10 < 0):
            return _sig(self, features, Side.SELL, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        tp_pts = self._TP_POINTS.get(self.timeframe)
        if tp_pts is None:
            return None
        tp_dist = tp_pts * point
        sl_dist = (tp_pts / 3.0) * point
        if side == Side.BUY:
            return entry_price - sl_dist, entry_price + tp_dist
        return entry_price + sl_dist, entry_price - tp_dist


class FollowTheTrendH4Strategy(_FollowTheTrendBase):
    """Follow the Trend: EMA(4,10) + ADX(28)/DI + MACD(5,10,4) — H4."""
    name = "follow_the_trend_h4"


class FollowTheTrendD1Strategy(_FollowTheTrendBase):
    """Follow the Trend: EMA(4,10) + ADX(28)/DI + MACD(5,10,4) — D1."""
    name = "follow_the_trend_d1"


class GoldmineXAUUSDStrategy(Strategy):
    """Faithful replica of the source app "Goldmine" strategy: BB(20,2) +
    Stochastic(5,3,3) for XAUUSD — D1. Gungnir's configured symbol for this
    instrument is "GOLD" (config.yaml), not "XAUUSD" — same underlying pair,
    different epic naming; `symbols` is scoped to "GOLD" to match it.

    Entry:
      Sell: price at/above the upper BB(20,2) band, the current candle is
            bearish (close < open), and Stochastic(5,3,3) — both %K and %D —
            is in the overbought zone (>80) AND sloping down.
      Buy:  mirror — price at/below the lower band, a bullish candle
            (close > open), Stochastic oversold (<20) and sloping up.
    Exit (custom_brackets): TP at the BB mid-line AS OF THE ENTRY BAR (not
    continuously tracked — "the level ... at which the position has been
    located at the opening moment"); SL at 1/3 of that TP distance from
    entry, in the opposite direction. Computed from raw price distance, not
    FX points, so it works for a non-currency instrument like gold.
    """

    name = "goldmine_xauusd"
    family = "meanrev"
    DEFAULTS = {
        "conviction_base": 0.5,
        "stoch_overbought": 80.0,
        "stoch_oversold": 20.0,
        "stoch_slope_confirm_enabled": 1.0,
        "fixed_exit_enabled": 1.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8), "stoch_overbought": (65.0, 90.0),
              "stoch_oversold": (10.0, 35.0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entry_bb_mid: float | None = None

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet) or not features.candles:
            return []
        candle = features.candles[-1]
        price = features.last_price
        base = self.p("conviction_base")
        overbought, oversold = self.p("stoch_overbought"), self.p("stoch_oversold")

        slope_down = slope_up = True
        if self.p("stoch_slope_confirm_enabled") > 0:
            slope_down = (features.stoch5_k < features.prev_stoch5_k
                         and features.stoch5_d < features.prev_stoch5_d)
            slope_up = (features.stoch5_k > features.prev_stoch5_k
                       and features.stoch5_d > features.prev_stoch5_d)

        if (price >= features.bb_upper and candle.close < candle.open
                and features.stoch5_k > overbought and features.stoch5_d > overbought
                and slope_down):
            self._entry_bb_mid = features.bb_mid
            return _sig(self, features, Side.SELL, base)
        elif (price <= features.bb_lower and candle.close > candle.open
                and features.stoch5_k < oversold and features.stoch5_d < oversold
                and slope_up):
            self._entry_bb_mid = features.bb_mid
            return _sig(self, features, Side.BUY, base)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0 or self._entry_bb_mid is None:
            return None
        tp = self._entry_bb_mid
        tp_dist = abs(entry_price - tp)
        if tp_dist <= 0:
            return None
        sl_dist = tp_dist / 3.0
        if side == Side.BUY:
            return entry_price - sl_dist, tp
        return entry_price + sl_dist, tp


class SpeculativeZigzagRSIStrategy(Strategy):
    """Faithful replica of the source app "Speculative" strategy: ZigZag
    (Depth=100) + RSI(14) — M15, EURUSD/GBPUSD.

    ZigZag itself isn't ported literally — a real ZigZag also filters by
    percentage Deviation and Backstep, neither of which the app changes from
    default, so "Depth=100" is really just "a confirmed swing point with a
    100-bar minimum separation." That's exactly what `_fractal_high`/
    `_fractal_low` (built for ema_stoch_rsi's swing stop) already detect —
    reused here with `order=depth` so a "ZigZag point" means a confirmed
    fractal extreme, not a literal MT4 ZigZag re-implementation.

    Entry:
      Sell: a ZigZag HIGH is confirmed on this exact bar AND RSI(14) > 70.
      Buy:  a ZigZag LOW is confirmed on this exact bar AND RSI(14) < 30.
    Exit (custom_brackets, FX pairs only): TP 60-100 points (`tp_points`,
    default 80); SL 15-20 points (`sl_points`, default 17.5).

    Directional lockout ("in case of S/L, we shall not open positions in
    this direction but wait for the opposite signal"): `on_position_closed`
    remembers a stop-out's side per symbol; same-direction signals are
    suppressed until a genuine opposite-direction signal fires, which also
    clears the block.
    """

    name = "speculative_zigzag_rsi"
    family = "meanrev"
    DEFAULTS = {
        "conviction_base": 0.5,
        "zigzag_depth": 100.0,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "tp_points": 80.0,     # app: 60-100 points
        "sl_points": 17.5,     # app: 15-20 points
        "fixed_exit_enabled": 1.0,
    }
    BOUNDS = {"conviction_base": (0.3, 0.8), "tp_points": (60.0, 100.0),
              "sl_points": (15.0, 20.0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._blocked_side: dict[str, Side] = {}

    def on_position_closed(self, symbol: str, side: Side, reason: str) -> None:
        if reason in ("stop-loss", "breakeven-stop"):
            self._blocked_side[symbol] = side

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet) or not features.candles:
            return []
        order = max(1, int(self.p("zigzag_depth")))
        window = 2 * order + 1
        candles = features.candles
        if len(candles) < window:
            return []
        # Restricting the lookback to exactly `window` candles makes
        # _fractal_high/_low check ONLY the single middle bar — i.e. "was a
        # swing point confirmed on exactly this bar," not "somewhere recently."
        recent = candles[-window:]
        pivot_high = _fractal_high(recent, order, window)
        pivot_low = _fractal_low(recent, order, window)
        rsi = features.rsi
        conviction = self.p("conviction_base")
        symbol = features.symbol
        blocked = self._blocked_side.get(symbol)

        if pivot_high is not None and rsi > self.p("rsi_overbought"):
            if blocked == Side.SELL:
                return []
            self._blocked_side.pop(symbol, None)
            return _sig(self, features, Side.SELL, conviction)
        elif pivot_low is not None and rsi < self.p("rsi_oversold"):
            if blocked == Side.BUY:
                return []
            self._blocked_side.pop(symbol, None)
            return _sig(self, features, Side.BUY, conviction)
        return []

    def custom_brackets(
        self, side: Side, entry_price: float, symbol: str
    ) -> tuple[float | None, float | None] | None:
        if self.p("fixed_exit_enabled") <= 0:
            return None
        point = _fx_point_size(symbol)
        if not point:
            return None
        tp_dist = self.p("tp_points") * point
        sl_dist = self.p("sl_points") * point
        if side == Side.BUY:
            return entry_price - sl_dist, entry_price + tp_dist
        return entry_price + sl_dist, entry_price - tp_dist


# Registry of all 26 strategies
KRAKEN_STRATEGIES = [
    CCIMACDStrategy,
    ParSARCCIM1Strategy,
    ParSARCCIM5Strategy,
    BBMACDStrategy,
    BBMACDSMAppStrategy,
    CCI200EMAStrategy,
    CCI200EMAPivotAppStrategy,
    EMAStochRSIStrategy,
    CCIReversalStrategy,
    ADXMomentumStrategy,
    BBRSICuttingStrategy,
    AwesomeOscillatorStrategy,
    AwesomeMACDAppStrategy,
    BBRSIStrategy,
    BBRSIM30Strategy,
    IntelligentTradingStrategy,
    MultiBBStrategy,
    MultiBBAppStrategy,
    MACDStochStrategy,
    AlligatorStrategy,
    HMADonchianM1Strategy,
    HMADonchianM5Strategy,
    HMADonchianM15Strategy,
    HMADonchianH1Strategy,
    HMADonchianH4Strategy,
    HMADonchianD1Strategy,
    FVGM1Strategy,
    FVGM5Strategy,
    FVGM15Strategy,
    FVGM30Strategy,
    FashionablyLateScalpM1Strategy,
    FashionablyLateScalpM5Strategy,
    EMA921ADXDMITrendM5Strategy,
    EMA921ADXDMITrendM15Strategy,
    EMA921EMA78TrendM5Strategy,
    EMA921EMA78TrendM15Strategy,
    FollowTheTrendH4Strategy,
    FollowTheTrendD1Strategy,
    GoldmineXAUUSDStrategy,
    SpeculativeZigzagRSIStrategy,
]
