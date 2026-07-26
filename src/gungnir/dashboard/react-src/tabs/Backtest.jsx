import React, { useState } from "react";
import { Card } from "../components.jsx";
import { Sparkline } from "../charts.jsx";
import { usd, signed } from "../format.js";
import { post } from "../api.js";

const FIELD = (label, children) => <div className="ctrl"><label>{label}</label>{children}</div>;

export default function Backtest() {
  const [form, setForm] = useState({
    symbol: "XBTUSD", strats: "1,2,3", consensus: false, balance: 10000, lookback: 7,
    sl: 1.5, tp: 3.0, spread: "", comm: "", slip: "",
  });
  const [state, setState] = useState({ status: "idle", result: null, error: null });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const run = async () => {
    setState({ status: "running", result: null, error: null });
    const strategies = form.strats.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
    const bps = (v) => { const x = parseFloat(v); return Number.isNaN(x) ? undefined : x; };
    try {
      const d = await post("/api/backtest/run", {
        symbol: form.symbol, strategies, consensus: form.consensus, starting_balance: +form.balance || 10000,
        lookback_days: +form.lookback, sl_pct: +form.sl, tp_pct: +form.tp,
        spread_bps: bps(form.spread), commission_bps: bps(form.comm), slippage_bps: bps(form.slip),
      });
      if (d.error) { setState({ status: "error", result: null, error: d.error }); return; }
      setState({ status: "done", result: d, error: null });
    } catch (e) {
      setState({ status: "error", result: null, error: e.message });
    }
  };

  const d = state.result;
  const entries = d ? Object.entries(d.strategies || {}) : [];
  const c = d?.costs || {};
  const srcTxt = d?.data_source === "capital.com" ? "real Capital.com data" : "synthetic data";

  return (
    <div className="page-pad stack">
      <h2 className="sec">Backtest</h2>
      <Card>
        <div className="controls">
          {FIELD("Symbol", <input value={form.symbol} onChange={set("symbol")} />)}
          {FIELD("Strategies (e.g. 1,2,3)", <input value={form.strats} onChange={set("strats")} />)}
          {FIELD(null, <label><input type="checkbox" checked={form.consensus} onChange={set("consensus")} /> Consensus (selected strategies)</label>)}
          {FIELD("Starting balance", <input type="number" step="100" value={form.balance} onChange={set("balance")} />)}
          {FIELD("Lookback (days)", <input type="number" value={form.lookback} onChange={set("lookback")} />)}
          {FIELD("Stop %", <input type="number" step="0.1" value={form.sl} onChange={set("sl")} />)}
          {FIELD("Take %", <input type="number" step="0.1" value={form.tp} onChange={set("tp")} />)}
          {FIELD("Spread (bps)", <input type="number" step="0.1" placeholder="0" value={form.spread} onChange={set("spread")} />)}
          {FIELD("Commission (bps)", <input type="number" step="0.1" placeholder="0" value={form.comm} onChange={set("comm")} />)}
          {FIELD("Slippage (bps)", <input type="number" step="0.1" placeholder="0" value={form.slip} onChange={set("slip")} />)}
          <button className="btn primary" onClick={run} disabled={state.status === "running"}>{state.status === "running" ? "Running…" : "Run Backtest"}</button>
        </div>
      </Card>

      {state.status === "error" && <Card><p className="neg-txt">{state.error}</p></Card>}
      {d && (
        <>
          <h2 className="sec">Results <span className="sec-dim">{d.symbol} · start {usd(d.starting_balance)} · {srcTxt} · spread {c.spread_bps || 0}/comm {c.commission_bps || 0}/slip {c.slippage_bps || 0} bps</span></h2>
          {!entries.length ? <Card><p>No results.</p></Card> : (
            <div className="bt-grid">
              {entries.map(([num, r]) => {
                const m = r.metrics || {};
                const pf = m.profit_factor == null ? "∞" : m.profit_factor;
                const pos = (m.total_return_pct || 0) >= 0;
                const curve = (m.equity_curve || []).map((p) => p.equity);
                return (
                  <div className="bt-card" key={num}>
                    <div className="bt-head"><span className="bt-num">S{num}</span><span className="bt-name">{r.name || ""}</span><span className="bt-bars">{r.bars} bars</span></div>
                    {curve.length > 1 && <div className="bt-chart"><Sparkline series={curve} color="var(--accent)" height={90} /></div>}
                    <div className="bt-metrics">
                      <div className="row"><span className="k">Trades</span><span className="v">{m.total_trades}</span></div>
                      <div className="row"><span className="k">Win rate</span><span className="v">{m.win_rate}%</span></div>
                      <div className="row"><span className="k">W / L</span><span className="v wl"><span className="pos-txt">{m.wins}</span> / <span className="neg-txt">{m.losses}</span></span></div>
                      <div className="row"><span className="k">Profit factor</span><span className="v">{pf}</span></div>
                      <div className="row"><span className="k">Final equity</span><span className="v">{usd(m.final_equity)}</span></div>
                      <div className="row"><span className="k">Total P&amp;L</span><span className="v" style={{ color: pos ? "var(--good)" : "var(--bad)" }}>{signed(m.total_pnl)}</span></div>
                      <div className="row"><span className="k">Total return</span><span className="v" style={{ color: pos ? "var(--good)" : "var(--bad)" }}>{m.total_return_pct}%</span></div>
                      <div className="row"><span className="k">Max drawdown</span><span className="v">{m.max_drawdown_pct}%</span></div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
