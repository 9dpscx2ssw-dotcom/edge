import React from "react";
import { usePoll, Empty } from "../components.jsx";
import { signed, cx } from "../format.js";
import { post } from "../api.js";

function MpsBlock({ mps }) {
  if (!mps) return null;
  const name = mps.strategy_name || (mps.strategy != null ? "S" + mps.strategy : "—");
  const pnl = mps.pnl || 0;
  const pf = mps.profit_factor != null ? mps.profit_factor.toFixed(2) : (pnl > 0 ? "∞" : "—");
  const wr = mps.win_rate != null ? mps.win_rate + "%" : "—";
  return (
    <div className="mc-mps">
      <div className="mps-head"><span className="mps-label">Most profitable strategy</span><span className="mps-name" title={name}>{mps.strategy != null ? "S" + mps.strategy + " · " : ""}{name}</span></div>
      <div className="mps-grid">
        <div className="mps-cell"><div className="k">Win rate</div><div className="v">{wr}</div></div>
        <div className="mps-cell"><div className="k">P&amp;L</div><div className="v" style={{ color: pnl >= 0 ? "var(--good)" : "var(--bad)" }}>{signed(pnl)}</div></div>
        <div className="mps-cell"><div className="k">Profit factor</div><div className="v">{pf}</div></div>
      </div>
    </div>
  );
}

function ConsensusBlock({ c }) {
  if (!c) return null;
  const score = +(c.score || 0), action = (c.action || "none").toLowerCase();
  const stances = +(c.stances || 0), opposing = Math.round((c.opposing || 0) * 100);
  const dg = c.diagnostics || {}, raw = Number.isFinite(+dg.raw_score) ? (+dg.raw_score).toFixed(2) : "—";
  const hz = Object.entries(dg.horizons || {}).map(([k, v]) => `${k} ${(+v).toFixed(2)}`).join(" · ");
  const state = action === "none" && !stances ? "NO VOTES" : action.toUpperCase();
  const color = action === "buy" ? "var(--good)" : action === "sell" ? "var(--bad)" : action === "veto" ? "var(--warn)" : "var(--text-faint)";
  return (
    <div className="mc-cons">
      <div className="cons-head"><span className="cons-label">Consensus</span><span className="cons-state" style={{ color }}>{state}</span></div>
      <div className="cons-mini-grid">
        <div className="cons-cell"><div className="k">Score</div><div className="v" style={{ color: score >= 0 ? "var(--good)" : "var(--bad)" }}>{score >= 0 ? "+" : ""}{score.toFixed(2)}</div></div>
        <div className="cons-cell"><div className="k">Raw</div><div className="v">{raw}</div></div>
        <div className="cons-cell"><div className="k">Votes</div><div className="v">{stances}</div></div>
        <div className="cons-cell"><div className="k">Opposition</div><div className="v">{opposing}%</div></div>
      </div>
      <div className="cons-note">{hz ? `Horizon weights: ${hz} ` : ""}{c.reason || "Weighted strategy consensus"}</div>
    </div>
  );
}

export default function Markets() {
  const { data, reload } = usePoll("/api/markets", { intervalMs: 5000 });
  const markets = data?.markets || [];
  const toggle = (sym, enabled) => post("/api/instruments/toggle", { symbol: sym, enabled }).then(reload);

  return (
    <div className="page-pad">
      <h2 className="sec">Markets <span className="sec-dim">toggle a market to enable/disable trading it</span></h2>
      {!markets.length ? <Empty>{data ? "No market data yet." : "Loading markets…"}</Empty> : (
        <div className="market-grid">
          {markets.map((m) => {
            const dir = m.rl_direction || "HOLD";
            const dc = dir === "BUY" ? "b-buy" : dir === "SELL" ? "b-sell" : "b-hold";
            return (
              <div className={cx("market-card", !m.enabled && "disabled")} key={m.symbol}>
                <div className="mc-head">
                  <div><div className="mc-sym">{m.symbol}</div><div className="mc-cat">{m.category || ""}</div></div>
                  <label className="switch"><input type="checkbox" checked={!!m.enabled} onChange={(e) => toggle(m.symbol, e.target.checked)} /><span className="slider" /></label>
                </div>
                <div className="mc-price">{m.price != null ? (+m.price).toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—"}</div>
                <div className="mc-row"><span>RL</span><span><span className={cx("badge", dc)}>{dir}</span></span></div>
                <div className="mc-row"><span>Trades</span><span>{m.trades || 0}</span></div>
                <div className="mc-row"><span>Win rate</span><span>{m.win_rate != null ? m.win_rate + "%" : "—"}</span></div>
                <div className="mc-row"><span>P&amp;L</span><span style={{ color: (m.pnl || 0) >= 0 ? "var(--good)" : "var(--bad)" }}>{signed(m.pnl || 0)}</span></div>
                <MpsBlock mps={m.mps} />
                <ConsensusBlock c={m.consensus} />
                {m.offline_action && <div className="mc-row"><span>Offline RL</span><span className={cx("badge", m.offline_action === "LONG" ? "b-buy" : m.offline_action === "SHORT" ? "b-sell" : "b-hold")}>{m.offline_action} · advisory</span></div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
