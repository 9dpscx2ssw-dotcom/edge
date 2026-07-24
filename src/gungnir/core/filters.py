"""Pre-trade context filters with strategy-aware regime policy."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..data.models import Side

_SESSIONS = {"Indices": [(13, 21)], "FX": [(7, 21)], "Commodities": [(7, 21)], "Crypto": [(0, 24)]}
_CATEGORIES = {
    "Indices": {"US100", "US500", "US30", "RTY", "J225", "DE40", "UK100", "HK50", "NAS100", "SPX500", "DJI30"},
    "Commodities": {"GOLD", "XAUUSD", "SILVER", "XAGUSD", "OIL", "WTI", "BRENT", "NATGAS"},
    "Crypto": {"BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD", "DOGEUSD", "ADAUSD", "LTCUSD", "XBTUSD"},
}
# Unknown names are intentionally not inferred as trend-following.
STRATEGY_FAMILIES = {
    "mean_reversion": "mean_reversion", "cci_reversal": "mean_reversion", "bb_rsi": "mean_reversion", "multi_bb": "mean_reversion", "bb_macd_sma": "mean_reversion", "bb_rsi_cutting": "mean_reversion",
    "parsar_cci_ema": "trend", "adx_momentum_ema": "trend", "alligator": "trend", "trend_following": "trend",
    "fvg_m1": "structure", "fvg_m5": "structure", "fvg_m15": "structure", "fvg_m30": "structure",
    "scalp_ema_vwap_m1": "scalp", "scalp_ema_vwap_m5": "scalp",
    "hma_dc_m1": "hybrid", "hma_dc_m5": "hybrid", "hma_dc_m15": "hybrid", "hma_dc_h1": "hybrid", "hma_dc_h4": "hybrid", "hma_dc_d1": "hybrid", "consensus": "ensemble",
}
_REGIME_MODES = {"observe", "shadow", "enforce"}
_NOISE_MODES = {"observe", "enforce"}


def category(symbol: str) -> str:
    for cat, members in _CATEGORIES.items():
        if symbol in members:
            return cat
    return "FX"


def calendar_allows(symbol: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return category(symbol) == "Crypto" or now.weekday() < 5


def in_session(symbol: str, hour: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return calendar_allows(symbol, now) and any(s <= now.hour < e for s, e in _SESSIONS.get(category(symbol), [(0, 24)]))


def classify_regime(f) -> str:
    """Compatibility fallback if canonical four-state regime is unavailable."""
    adx = float(getattr(f, "adx", 0.0) or 0.0)
    if adx >= 25.0:
        return "trend_up" if (f.ema_fast or 0) >= (f.ema_slow or 0) else "trend_down"
    return "range"


def strategy_family(strategy: str) -> str:
    return STRATEGY_FAMILIES.get(strategy, "unknown")


@dataclass(frozen=True)
class RegimeDecision:
    mode: str
    policy_version: str
    regime: str
    family: str
    would_veto: bool
    reason: str | None = None


@dataclass
class FilterConfig:
    trend: bool = False
    volatility: bool = False
    volume: bool = False
    session: bool = False
    spread: bool = False
    regime: bool = False
    vol_min: float = 0.0001
    vol_max: float = 0.03
    min_volume_ratio: float = 0.5
    max_spread_bps: float = 15.0
    adx_trend: float = 25.0
    regime_mode: str = "observe"
    regime_policy_version: str = "shadow-regime-v1"
    regime_rules: list[dict[str, str]] = field(default_factory=list)
    # No-trend-structure filter: block entries where the fast/slow EMA spread is
    # below ``noise_min_ema_atr`` ATRs (chop, no established trend). Ships in
    # ``observe`` (tags every decision but blocks nothing) so the signal can be
    # validated against realized PnL before it ever gates a trade.
    noise: bool = False
    noise_mode: str = "observe"          # observe | enforce
    noise_min_ema_atr: float = 0.4

    @classmethod
    def from_dict(cls, d: dict | None) -> "FilterConfig":
        d = d or {}
        f = cls()
        for k in vars(f):
            if k not in d or d[k] is None:
                continue
            if k == "regime_rules":
                value = d[k] if isinstance(d[k], list) else []
                f.regime_rules = [{str(key): str(val) for key, val in rule.items()} for rule in value if isinstance(rule, dict)]
            elif k in {"regime_mode", "regime_policy_version", "noise_mode"}:
                setattr(f, k, str(d[k]))
            else:
                setattr(f, k, type(getattr(f, k))(d[k]))
        if f.regime_mode not in _REGIME_MODES:
            f.regime_mode = "observe"
        if f.noise_mode not in _NOISE_MODES:
            f.noise_mode = "observe"
        return f


def merge_filter_overrides(base: dict | None, overrides: dict | None) -> dict:
    """Overlay dashboard-owned settings without discarding configured policy.

    Runtime control files intentionally contain only fields changed through the UI.
    A shallow overlay preserves static policy metadata/rules that the UI does not
    edit, while allowing an explicit runtime `regime_mode` to supersede config.
    """
    merged = dict(base or {})
    merged.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return merged


def evaluate_regime(strategy: str, features, cfg: FilterConfig, regime: str | None = None) -> RegimeDecision:
    """Resolve explicit family × canonical regime; unknowns are never guessed."""
    mode = cfg.regime_mode if cfg.regime_mode in _REGIME_MODES else "observe"
    current = regime or classify_regime(features)
    family = strategy_family(strategy)
    for rule in cfg.regime_rules:
        if rule.get("family") == family and rule.get("regime") == current and rule.get("action") == "avoid":
            return RegimeDecision(mode, cfg.regime_policy_version, current, family, True, "family_regime_avoid")
    return RegimeDecision(mode, cfg.regime_policy_version, current, family, False)


def evaluate_noise(features, cfg: FilterConfig) -> tuple[bool, float | None]:
    """No-trend-structure reading for one decision.

    Returns ``(would_block, ema_spread_in_atr)``. ``would_block`` is True when
    the fast/slow EMA spread is below ``noise_min_ema_atr`` ATRs — a chop entry
    with no established trend. Pure and side-effect-free; the caller decides
    whether to act (``enforce``) or merely tag it (``observe``). ATR/EMA missing
    ⇒ ``(False, None)`` so a thin feature set never blocks.
    """
    ef = getattr(features, "ema_fast", None)
    es = getattr(features, "ema_slow", None)
    atr = getattr(features, "atr", None)
    if ef is None or es is None or not atr or atr <= 0:
        return False, None
    ext = abs(float(ef) - float(es)) / float(atr)
    return ext < cfg.noise_min_ema_atr, round(ext, 4)


def market_regime_filter(signal, sentiment) -> tuple[bool, str | None]:
    if sentiment is None or sentiment.confidence < 0.5:
        return True, None
    if sentiment.score < -0.7 and sentiment.confidence > 0.7 and signal.side == Side.BUY:
        return False, "sentiment_panic"
    if sentiment.score > 0.7 and sentiment.confidence > 0.7 and signal.side != Side.BUY:
        return False, "sentiment_euphoria"
    return True, None


def _spread_bps(features) -> float | None:
    ob = getattr(features, "orderbook", None)
    last = features.last_price or 0.0
    if ob is None or not getattr(ob, "spread", None) or not last:
        return None
    return ob.spread / last * 10_000.0


def apply(signal, features, strategy: str, cfg: FilterConfig, symbol: str, now: datetime | None = None, regime: str | None = None) -> tuple[bool, str | None]:
    """Only a matching policy in explicit enforce mode can veto by regime."""
    if signal.side == Side.FLAT:
        return True, None
    now = now or datetime.now(timezone.utc)
    if cfg.session:
        windows = _SESSIONS.get(category(symbol), [(0, 24)])
        if not calendar_allows(symbol, now) or not any(s <= now.hour < e for s, e in windows):
            return False, "session"
    if cfg.spread:
        sb = _spread_bps(features)
        if sb is not None and sb > cfg.max_spread_bps:
            return False, "spread"
    if cfg.volatility:
        last = features.last_price or 0.0
        vol = (features.atr / last) if last else 0.0
        if vol < cfg.vol_min or vol > cfg.vol_max:
            return False, "volatility"
    if cfg.volume:
        candles = getattr(features, "candles", None) or []
        vols = [getattr(c, "volume", 0.0) or 0.0 for c in candles[-20:]]
        if len(vols) >= 5 and sum(vols) > 0:
            avg = sum(vols) / len(vols)
            if avg > 0 and vols[-1] < cfg.min_volume_ratio * avg:
                return False, "volume"
    if cfg.trend:
        up = (features.ema_fast or 0) >= (features.ema_slow or 0)
        if (signal.side == Side.BUY and not up) or (signal.side == Side.SELL and up):
            return False, "trend"
    if cfg.regime:
        decision = evaluate_regime(strategy, features, cfg, regime)
        if decision.would_veto and decision.mode == "enforce":
            return False, "regime"
    if cfg.noise and cfg.noise_mode == "enforce":
        would, _ = evaluate_noise(features, cfg)
        if would:
            return False, "noise"
    return True, None
