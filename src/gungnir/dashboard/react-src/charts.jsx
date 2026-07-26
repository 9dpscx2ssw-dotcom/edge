import { useEffect, useRef } from "react";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// Canvas 2D can't resolve CSS custom properties (addColorStop/strokeStyle need
// an actual color string) — accept either a raw color or a "var(--x)" literal
// and resolve the latter against :root before it reaches the 2D context.
function resolveColor(c) {
  if (!c) return c;
  const m = /^var\((--[\w-]+)\)$/.exec(c.trim());
  return m ? css(m[1]) : c;
}

function useCanvas(draw, deps) {
  const ref = useRef(null);
  useEffect(() => {
    const cvs = ref.current;
    if (!cvs) return;
    const render = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = cvs.clientWidth, h = cvs.clientHeight;
      if (!w || !h) return;
      cvs.width = w * dpr; cvs.height = h * dpr;
      const ctx = cvs.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      draw(ctx, w, h);
    };
    render();
    const ro = new ResizeObserver(render);
    ro.observe(cvs);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

/** Filled line/area sparkline — used for reward trend, cumulative reward, per-strategy P&L curves. */
export function Sparkline({ series, color, height = 46 }) {
  const ref = useCanvas((ctx, w, h) => {
    if (!series || series.length < 2) return;
    const stroke = resolveColor(color) || css("--accent");
    let min = Math.min(...series), max = Math.max(...series);
    if (min === max) { min -= 1; max += 1; }
    const zeroY = h - ((0 - min) / (max - min)) * h;
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, zeroY); ctx.lineTo(w, zeroY); ctx.stroke();
    const stepX = w / (series.length - 1);
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, stroke + "44"); grad.addColorStop(1, stroke + "00");
    ctx.beginPath();
    series.forEach((v, i) => { const x = i * stepX, y = h - ((v - min) / (max - min)) * h; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    series.forEach((v, i) => { const x = i * stepX, y = h - ((v - min) / (max - min)) * h; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = stroke; ctx.lineWidth = 1.6; ctx.stroke();
    const ly = h - ((series[series.length - 1] - min) / (max - min)) * h;
    ctx.fillStyle = stroke; ctx.beginPath(); ctx.arc(w - 1.5, ly, 2.4, 0, Math.PI * 2); ctx.fill();
  }, [series, color, height]);
  return <canvas ref={ref} className="spark" style={{ height }} />;
}

/** Two-series line chart (real vs shadow equity curves), starting both at `base`. */
export function EquityChart({ real, shadow, base, height = 220 }) {
  const ref = useCanvas((ctx, w, h) => {
    const realPts = [base, ...real.map((p) => p.equity)];
    const shadowPts = [base, ...shadow.map((p) => p.equity)];
    const n = Math.max(realPts.length, shadowPts.length, 2);
    const all = [...realPts, ...shadowPts];
    let min = Math.min(...all), max = Math.max(...all);
    if (min === max) { min -= 1; max += 1; }
    const pad = 8;
    const line = (pts, color, dash) => {
      if (pts.length < 2) return;
      const stepX = (w - pad * 2) / (n - 1);
      ctx.setLineDash(dash || []);
      ctx.beginPath();
      pts.forEach((v, i) => { const x = pad + i * stepX, y = h - pad - ((v - min) / (max - min)) * (h - pad * 2); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
    };
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
    const zeroY = h - pad - ((base - min) / (max - min)) * (h - pad * 2);
    ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(pad, zeroY); ctx.lineTo(w - pad, zeroY); ctx.stroke(); ctx.setLineDash([]);
    line(realPts, css("--good"));
    line(shadowPts, "#e83e8c", [4, 3]);
  }, [real, shadow, base, height]);
  return <canvas ref={ref} className="spark" style={{ height }} />;
}

/** Vertical bar chart — per-strategy pooled P&L. */
export function BarChart({ labels, data, height = 160 }) {
  const ref = useCanvas((ctx, w, h) => {
    if (!data.length) return;
    const pad = 22;
    const max = Math.max(1, ...data.map((v) => Math.abs(v)));
    const zeroY = h / 2;
    const bw = (w - pad * 2) / data.length;
    ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad, zeroY); ctx.lineTo(w - pad, zeroY); ctx.stroke();
    data.forEach((v, i) => {
      const bh = (Math.abs(v) / max) * (h / 2 - 14);
      const x = pad + i * bw + bw * 0.15;
      ctx.fillStyle = v >= 0 ? css("--good") : css("--bad");
      ctx.fillRect(x, v >= 0 ? zeroY - bh : zeroY, bw * 0.7, bh);
    });
    ctx.fillStyle = css("--text-faint"); ctx.font = "9px monospace"; ctx.textAlign = "center";
    labels.forEach((lbl, i) => { if (data.length <= 20) ctx.fillText(lbl, pad + i * bw + bw / 2, h - 4); });
  }, [labels, data, height]);
  return <canvas ref={ref} className="spark" style={{ height }} />;
}

/** Take-rate / epsilon dual-line chart with a fixed collapse-floor dashed reference. */
export function TakeRateChart({ series, height = 150 }) {
  const ref = useCanvas((ctx, w, h) => {
    if (!series || series.length < 2) return;
    let lastVal = 0;
    const take = series.map((r) => { if (r.take_rate != null) lastVal = r.take_rate; return lastVal; });
    const eps = series.map((r) => r.epsilon);
    const line = (vals, color, width, dash) => {
      const stepX = w / (vals.length - 1);
      ctx.setLineDash(dash || []);
      ctx.beginPath();
      vals.forEach((v, i) => { const x = i * stepX, y = h - v * h; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke(); ctx.setLineDash([]);
    };
    line(new Array(take.length).fill(0.05), css("--bad"), 1, [3, 3]);
    line(eps, css("--text-faint"), 1.3);
    line(take, css("--accent"), 2);
  }, [series, height]);
  return <canvas ref={ref} className="spark" style={{ height }} />;
}
