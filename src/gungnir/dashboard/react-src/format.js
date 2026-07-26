export const usd = (n) => (n == null || Number.isNaN(n)) ? "—" : "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const signed = (n) => (n == null || Number.isNaN(n)) ? "—" : (n < 0 ? "-" : "+") + usd(n);
export const pct = (v, d = 1) => (v == null || Number.isNaN(v)) ? "—" : (v * 100).toFixed(d) + "%";
export const pctRaw = (v, d = 1) => (v == null || Number.isNaN(v)) ? "—" : (+v).toFixed(d) + "%";
export const cx = (...xs) => xs.filter(Boolean).join(" ");
export const pfBucket = (pf) => (pf == null ? null : pf >= 1 ? "good" : pf >= 0.5 ? "warn" : "bad");
export const pfClass = (pf) => pfBucket(pf) || "none";
export function timeAgo(iso, now) {
  if (!iso) return "—";
  const diffMs = (now || new Date()) - new Date(iso);
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return diffMin + "m ago";
  const h = Math.floor(diffMin / 60), m = diffMin % 60;
  if (h < 24) return h + "h" + (m ? " " + m + "m" : "") + " ago";
  return Math.floor(h / 24) + "d ago";
}

// Second-resolution "Xs/Xm Ys/Xh Ym/Xd ago" — timeAgo() above rounds to whole
// minutes, too coarse for a live-ticking freshness indicator on a signal
// that's seconds old.
export function ageLabel(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + "s ago";
  const m = Math.floor(s / 60), rs = s % 60;
  if (m < 60) return m + "m" + (rs ? " " + rs + "s" : "") + " ago";
  const h = Math.floor(m / 60), rm = m % 60;
  if (h < 24) return h + "h" + (rm ? " " + rm + "m" : "") + " ago";
  return Math.floor(h / 24) + "d ago";
}

// Freshness band scaled to the strategy's own timeframe: an M1 scalp signal
// is stale in seconds, a D1 signal in hours — a fixed cutoff would mislabel
// one or the other. "Aging" starts at ~1/3 of one bar, "stale" at ~2 bars.
const TIMEFRAME_MINUTES = {
  "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, multi: 15,
};
export function freshnessBand(ageMs, timeframe) {
  const barMin = TIMEFRAME_MINUTES[timeframe] || 15;
  const ageMin = ageMs / 60000;
  if (ageMin < barMin / 3) return "fresh";
  if (ageMin < barMin * 2) return "aging";
  return "stale";
}
