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
