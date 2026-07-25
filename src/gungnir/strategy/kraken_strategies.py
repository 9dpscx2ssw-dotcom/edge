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


def _fx_point_size(symbol: str) -> float | None:
    """Standard FX pip size: 0.01 for JPY-quoted pairs, 0.0001 otherwise.

    None for anything that isn't a genuine 6-letter ISO currency pair
    (indices, commodities, crypto like BTCUSD) — "points" in the
    app-strategy sense isn't a meaningful unit there, so callers should fall
    back to the generic ATR-based stop instead of guessing a tick size.
    """
    from ..execution.fx import _CCY
    s = symbol.upper()
    if len(s) == 6 and s[:3] in _CCY and s[3:] in _CCY:
        return 0.01 if s.endswith("JPY") else 0.0001
    return None


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


class ParSARCCIStrategy(Strategy):
    """S2: Parabolic SAR + CCI(45) + EMA(50) — M1, source-strategy-accurate.

    Entry compares the SAR *value* to the EMA line (the app spec's "SAR point
    above/below the EMA's line"), not price to EMA — those aren't the same
    test. Optionally confirmed against an EMA(21) on a higher timeframe
    (``confirm_timeframe``, M5 by default), mirroring the source app's
    dual-timeframe filter (EMA50/M1 + EMA21/M5); toggle off via the
    ``mtf_confirm_enabled`` param. Exit trailing (stop follows the EMA line,
    per the app's "Stop Loss level should be placed at the EMA level") is
    opt-in via ``ema_trail_enabled`` — see Agent._manage_exits.
    """

    name = "parsar_cci_ema"
    family = "trend"
    confirm_timeframe = "5m"
    trail_ema_period = 50
    DEFAULTS = {
        "cci_threshold": 100.0,
        "conviction_base": 0.5,
        "mtf_confirm_enabled": 1.0,   # 0 disables the M5/EMA21 confluence check
        "ema_trail_enabled": 1.0,     # 0 disables the EMA-line trailing stop
    }
    BOUNDS = {"cci_threshold": (50.0, 200.0), "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        thr = self.p("cci_threshold")
        base = self.p("conviction_base")
        cci = features.cci45
        price = features.last_price
        conviction = base + 0.3 * min(max(abs(cci) - thr, 0.0) / max(thr, 1e-9), 1.0)

        # Higher-timeframe confluence: only take the M1 signal if price sits on
        # the right side of the M5 EMA21 trend filter. `_confirm_features` is
        # attached by the agent each cycle from `confirm_timeframe`'s feature
        # set; absent (thin data / toggled off) ⇒ the check is skipped.
        confirm = getattr(self, "_confirm_features", None)
        mtf_ok_buy = mtf_ok_sell = True
        if confirm is not None and self.p("mtf_confirm_enabled") > 0:
            mtf_ok_buy = price > confirm.ema21
            mtf_ok_sell = price < confirm.ema21

        if features.sar > features.ema50 and cci > thr and mtf_ok_buy:
            return _sig(self, features, Side.BUY, conviction)
        elif features.sar < features.ema50 and cci < -thr and mtf_ok_sell:
            return _sig(self, features, Side.SELL, conviction)
        return []


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
    """S6: CCI(14) Reversal — H1."""

    name = "cci_reversal"
    family = "meanrev"
    DEFAULTS = {"cci_threshold": 100.0, "conviction_base": 0.5}
    BOUNDS = {"cci_threshold": (50.0, 250.0), "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        thr = self.p("cci_threshold")
        base = self.p("conviction_base")
        cci = features.cci14
        conviction = base + 0.3 * min(max(abs(cci) - thr, 0.0) / max(thr, 1e-9), 1.0)
        if cci < -thr:
            return _sig(self, features, Side.BUY, conviction)
        elif cci > thr:
            return _sig(self, features, Side.SELL, conviction)
        return []


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
    """S8: BB(20,2) + ADX(14) + RSI(7) — M5."""

    name = "bb_rsi_cutting"
    family = "meanrev"
    DEFAULTS = {"rsi_oversold": 30.0, "rsi_overbought": 70.0, "adx_max": 30.0,
                "conviction_base": 0.5}
    BOUNDS = {"rsi_oversold": (10.0, 40.0), "rsi_overbought": (60.0, 90.0),
              "adx_max": (20.0, 50.0), "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        rsi = features.rsi
        conviction = self.p("conviction_base")
        if features.adx >= self.p("adx_max"):
            return []
        if price <= features.bb_lower and rsi < self.p("rsi_oversold"):
            return _sig(self, features, Side.BUY, conviction)
        elif price >= features.bb_upper and rsi > self.p("rsi_overbought"):
            return _sig(self, features, Side.SELL, conviction)
        return []


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


class BBRSIStrategy(Strategy):
    """S10: Bollinger Bands(20,2) + RSI(11) — M15."""

    name = "bb_rsi"
    family = "meanrev"
    DEFAULTS = {"rsi_overbought": 70.0, "rsi_oversold": 30.0, "conviction_base": 0.5}
    BOUNDS = {"rsi_overbought": (60.0, 90.0), "rsi_oversold": (10.0, 40.0),
              "conviction_base": (0.3, 0.8)}

    def generate(self, features: KrakenFeatureSet) -> list[Signal]:
        if not isinstance(features, KrakenFeatureSet):
            return []
        price = features.last_price
        rsi = features.rsi
        conviction = self.p("conviction_base")
        if rsi > self.p("rsi_overbought") and price > features.bb_upper:
            return _sig(self, features, Side.BUY, conviction)
        elif rsi < self.p("rsi_oversold") and price < features.bb_lower:
            return _sig(self, features, Side.SELL, conviction)
        return []


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
    """S14: Williams Alligator(13/8/5) + SMA(144) — M15."""

    name = "alligator"
    family = "trend"
    DEFAULTS = {"conviction_base": 0.5}
    BOUNDS = {"conviction_base": (0.3, 0.8)}

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


# Registry of all 26 strategies
KRAKEN_STRATEGIES = [
    CCIMACDStrategy,
    ParSARCCIStrategy,
    BBMACDStrategy,
    BBMACDSMAppStrategy,
    CCI200EMAStrategy,
    CCI200EMAPivotAppStrategy,
    EMAStochRSIStrategy,
    CCIReversalStrategy,
    ADXMomentumStrategy,
    BBRSICuttingStrategy,
    AwesomeOscillatorStrategy,
    BBRSIStrategy,
    IntelligentTradingStrategy,
    MultiBBStrategy,
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
]
