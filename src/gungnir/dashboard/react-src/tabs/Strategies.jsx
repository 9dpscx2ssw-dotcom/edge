import React, { useMemo, useState } from "react";
import { Card, Badge, PFPill, usePoll, Empty } from "../components.jsx";
import { Sparkline, BarChart } from "../charts.jsx";
import { signed, cx, pfBucket, pfClass } from "../format.js";
import { post } from "../api.js";

function ModeSeg({ mode, onSet, isConsensus, name }) {
  const set = (m) => {
    if (m === "live") {
      const msg = isConsensus ? "Set consensus to LIVE?\n\nThe aggregator will place REAL orders on the connected broker account (demo or real depending on your .env)."
        : `Promote ${name} to LIVE?\n\nIts signals will place REAL orders on the connected broker account (demo or real depending on your .env).`;
      if (!window.confirm(msg)) return;
    }
    onSet(m);
  };
  return (
    <div className="mode-seg" title="off = disabled · shadow = paper-trade only · live = real orders on the connected account">
      {["off", "shadow", "live"].map((m) => (
        <button key={m} className={cx("ms-btn", mode === m && `on-${m}`)} onClick={() => set(m)}>{m === "shadow" ? "SHDW" : m.toUpperCase()}</button>
      ))}
    </div>
  );
}

function TopSymbols({ rows }) {
  if (!rows || !rows.length) return null;
  return (
    <div className="sc-tops">
      <div className="st-label">Best symbols</div>
      <div className="st-row st-head"><span className="st-sym">Symbol</span><span>Win</span><span>Trades</span><span>P&amp;L</span></div>
      {rows.map((r, i) => (
        <div className="st-row" key={i}><span className="st-sym">{r.symbol}</span><span>{r.win_rate != null ? r.win_rate + "%" : "—"}</span><span>{r.trades || 0}</span>
          <span style={{ color: (r.pnl || 0) >= 0 ? "var(--good)" : "var(--bad)" }}>{signed(r.pnl || 0)}</span></div>
      ))}
    </div>
  );
}

function InstrumentMatrix({ m }) {
  const inst = m.instruments || [], strats = m.strategies || [], cells = m.cells || [];
  if (!inst.length || !strats.length) return <Empty>No instrument × strategy performance data yet.</Empty>;
  const byKey = {};
  cells.forEach((c) => { byKey[c.symbol + "|" + c.strategy] = c; });
  const pnls = cells.map((c) => Number(c.pnl) || 0).filter((v) => v !== 0);
  const maxPnl = Math.max(1, ...pnls.map((v) => Math.abs(v)));
  const money = (v) => { const n = Number(v) || 0; return (n >= 0 ? "+$" : "-$") + Math.abs(n).toFixed(2); };
  return (
    <>
      <div className="is-legend"><span className="swatch pos" />positive P/L <span className="swatch neg" />negative P/L <span className="swatch flat" />no closed trades <span className="is-legend-tail">cell: win rate / P/L</span></div>
      <div className="tscroll">
        <table className="is-table">
          <thead><tr><th className="left">Instrument</th>{strats.map((s) => <th key={s.strategy} title={s.name}>{s.strategy === 0 ? "CON" : "S" + s.strategy}</th>)}</tr></thead>
          <tbody>
            {inst.map((sym) => (
              <tr key={sym}><td className="left"><b>{sym}</b></td>
                {strats.map((st) => {
                  const c = byKey[sym + "|" + st.strategy];
                  if (!c) return <td key={st.strategy}><span className="is-cell is-flat">—</span></td>;
                  const pnl = Number(c.pnl) || 0, wr = c.win_rate == null ? "—" : c.win_rate + "%";
                  const heat = (0.12 + 0.38 * Math.min(1, Math.abs(pnl) / maxPnl)).toFixed(2);
                  const clsName = pnl > 0 ? "is-pos" : pnl < 0 ? "is-neg" : "is-flat";
                  return (
                    <td key={st.strategy} title={`${sym} × ${c.strategy_name || "S" + st.strategy}: win rate ${wr}, P/L ${money(pnl)}, ${c.trades || 0} closed trades`}>
                      <span className={cx("is-cell", clsName)} style={{ "--heat": heat }}>{wr}<br /><small>{money(pnl)}</small></span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function BacktestHeatmap() {
  const bt = usePoll("/api/backtest", { intervalMs: 60000 });
  const [filters, setFilters] = useState({ good: true, warn: true, bad: true });
  const rows = useMemo(() => {
    if (!bt.data || !bt.data.strategies) return null;
    return Object.entries(bt.data.strategies).map(([name, v]) => ({ name, ...v }));
  }, [bt.data]);
  if (bt.loading && !rows) return <Card title="Strategy backtest PF"><Empty>Loading…</Empty></Card>;
  if (!rows || !rows.length) {
    return (
      <Card title="Strategy backtest PF" dim="— no cached run">
        <div className="note-box">No <code>data/backtest_all_strategies.json</code> found. Run <code>python scripts/backtest_all_strategies.py</code> to populate this heatmap — it replays every registered strategy against cached candles with the effective runtime filters.</div>
      </Card>
    );
  }
  const filtered = rows.filter((s) => { const b = pfBucket(s.profit_factor); return !b || filters[b]; })
    .sort((a, b) => (b.profit_factor ?? -1) - (a.profit_factor ?? -1));
  return (
    <Card title="Strategy backtest PF" dim={`— ${rows.length} strategies, last cached run`}
      right={
        <div className="heatmap-filters">
          {["good", "warn", "bad"].map((k) => (
            <label key={k} className="check inline"><input type="checkbox" checked={filters[k]} onChange={() => setFilters((f) => ({ ...f, [k]: !f[k] }))} />{k === "good" ? "PF≥1" : k === "warn" ? "0.5–1" : "<0.5"}</label>
          ))}
        </div>
      }
      foot="Source: data/backtest_all_strategies.json — last 1000 cached bars per symbol, runtime filters replayed. This is offline evidence, not live performance.">
      <div className="tscroll">
        <table>
          <thead><tr><th className="left">Strategy</th><th>PF</th><th>Trades</th><th>Win %</th><th>P&amp;L</th></tr></thead>
          <tbody>
            {filtered.map((s) => (
              <tr className="strat-row" key={s.name}>
                <td className="left">{s.name} <span className="tf-tag">{s.timeframe}</span></td>
                <td><PFPill pf={s.profit_factor} /></td>
                <td>{s.trades}</td>
                <td>{s.win_rate == null ? "—" : s.win_rate.toFixed(0) + "%"}</td>
                <td className={cx("pnl", s.pnl > 0 ? "pos" : s.pnl < 0 ? "neg" : "zero")}>{s.pnl == null ? "—" : (s.pnl >= 0 ? "+" : "") + "$" + s.pnl.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function Strategies() {
  const { data, reload } = usePoll("/api/strategies", { intervalMs: 5000 });
  const ss = data?.strategies || [];
  const traded = ss.filter((s) => s.performance && s.performance.count > 0);
  const base = (traded.length ? traded : ss.slice(0, 12));

  const setStratMode = (name, mode) => post(`/api/strategies/${encodeURIComponent(name)}/mode`, { mode }).then(reload).catch((e) => window.alert("Strategy mode update failed for " + name + ": " + e.message));
  const setConsensusMode = (mode) => post("/api/consensus/mode", { mode }).then(reload).catch((e) => window.alert("Failed: " + e.message));

  return (
    <div className="page-pad stack">
      <h2 className="sec">Strategy P&amp;L</h2>
      <Card><BarChart labels={base.map((s) => (s.strategy === 0 ? "CON" : "S" + s.strategy))} data={base.map((s) => s.performance?.pnl || 0)} /></Card>

      <BacktestHeatmap />

      <h2 className="sec">Strategies</h2>
      {!ss.length && <Empty>Loading strategies…</Empty>}
      <div className="strat-grid">
        {ss.map((s) => {
          const p = s.performance || {};
          const pnl = p.pnl || 0;
          const md = s.mode || "off";
          const isConsensus = s.strategy === 0;
          return (
            <div className={cx("strat-card", isConsensus && "consensus-card", !s.enabled && "off")} key={s.strategy}>
              <div className="sc-head">
                <span className="sc-num">{isConsensus ? "CON" : "S" + s.strategy}</span>
                <span className="sc-name">{s.name}</span>
                <ModeSeg mode={md} name={s.name} isConsensus={isConsensus} onSet={(m) => isConsensus ? setConsensusMode(m) : setStratMode(s.name, m)} />
              </div>
              <div className="sc-desc">
                <b className="sc-tf">{s.timeframe || "—"}</b> · {s.indicators || ""}
                {s.excluded_symbols?.length ? <><br /><span className="sc-pruned" title={s.excluded_symbols.join(", ")}>⛔ {s.excluded_symbols.length} symbol{s.excluded_symbols.length > 1 ? "s" : ""} pruned (learned)</span></> : null}
              </div>
              {p.curve?.length > 1 && <div className="sc-spark"><Sparkline series={p.curve} color={p.curve[p.curve.length - 1] >= 0 ? "var(--good)" : "var(--bad)"} height={32} /></div>}
              <div className="sc-stats">
                <div className="sc-stat"><div className="lbl">P&amp;L</div><div className="val" style={{ color: pnl >= 0 ? "var(--good)" : "var(--bad)" }}>{signed(pnl)}</div></div>
                <div className="sc-stat"><div className="lbl">Win rate</div><div className="val">{p.win_rate || 0}%</div></div>
                <div className="sc-stat"><div className="lbl">W / L</div><div className="val wl"><span className="w">{p.wins || 0}</span>/<span className="l">{p.losses || 0}</span></div></div>
              </div>
              <div className="sc-stats">
                <div className="sc-stat"><div className="lbl">Trades</div><div className="val">{p.count || 0}</div></div>
                <div className="sc-stat"><div className="lbl">Profit factor</div><div className="val">{p.profit_factor == null ? "∞" : p.profit_factor}</div></div>
                <div className="sc-stat"><div className="lbl">Avg conf</div><div className="val">{p.avg_confidence != null ? p.avg_confidence + "%" : "—"}</div></div>
              </div>
              <TopSymbols rows={s.top_symbols} />
            </div>
          );
        })}
      </div>

      <h2 className="sec">Instrument × strategy</h2>
      <Card>{data?.instrument_strategy ? <InstrumentMatrix m={data.instrument_strategy} /> : <Empty>Loading instrument strategy matrix…</Empty>}</Card>
    </div>
  );
}
