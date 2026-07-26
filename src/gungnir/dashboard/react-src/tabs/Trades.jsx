import React from "react";
import { Card, usePoll, Empty } from "../components.jsx";
import { signed, cx } from "../format.js";
import { post } from "../api.js";

const ts19 = (s) => (s || "").slice(0, 19).replace("T", " ") || "—";
const byMode = (rows) => ({
  real: rows.filter((t) => ["real", "live"].includes(String(t.mode || "").toLowerCase())),
  shadow: rows.filter((t) => !["real", "live"].includes(String(t.mode || "").toLowerCase())),
});

function TradeSection({ title, headers, rows, empty }) {
  return (
    <>
      <h4 className="subhead-accent">{title}</h4>
      <div className="tscroll">
        <table className="data-table">
          <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{rows.length ? rows : <tr><td className="faint" colSpan={headers.length}>{empty}</td></tr>}</tbody>
        </table>
      </div>
    </>
  );
}

export default function Trades({ status, reload }) {
  const closed = usePoll("/api/trades", { intervalMs: 5000 });
  const opens = status?.open_trades || [];
  const views = status?.views || {};
  const om = byMode(opens);
  const cm = byMode(closed.data || []);

  const closePosition = (sym) => { if (window.confirm(`Close ${sym}?`)) post("/api/trades/close", { symbols: [sym] }).then(() => { window.alert(`Close request sent for ${sym}`); reload(); closed.reload(); }).catch((e) => window.alert("Error: " + e.message)); };
  const closeAll = () => { if (window.confirm("Close ALL open positions?")) post("/api/trades/close", { symbols: null }).then(() => { window.alert("Close-all request sent"); reload(); closed.reload(); }).catch((e) => window.alert("Error: " + e.message)); };

  const openHeaders = ["Opened", "Symbol", "Dir", "Vol", "Entry", "Current Price", "TP", "SL", "Running P&L", "Conf", "Strat", "Action"];
  const openRows = (rs) => rs.map((t, i) => {
    const q = views[t.symbol] || {};
    const cp = t.current_price ?? q.live_price ?? q.price;
    return (
      <tr key={i}>
        <td>{ts19(t.opened_at)}</td><td>{t.symbol}</td><td>{t.direction}</td><td>{t.size ?? "—"}</td><td>{t.entry ?? "—"}</td><td>{cp ?? "—"}</td>
        <td>{t.tp ?? t.take_profit ?? "—"}</td><td>{t.sl ?? t.stop_loss ?? "—"}</td>
        <td className={(t.running_pnl || 0) >= 0 ? "pos-txt" : "neg-txt"}>{t.running_pnl != null ? signed(t.running_pnl) : "—"}</td>
        <td>{t.confidence != null ? t.confidence + "%" : "—"}</td><td className="faint small">{t.strategy || "—"}</td>
        <td><button className="btn-ghost" onClick={() => closePosition(t.symbol)}>Close</button></td>
      </tr>
    );
  });

  const closedHeaders = ["Opened", "Closed", "Symbol", "Side", "Vol", "Entry", "Current Price", "TP", "SL", "P&L", "MFE", "MAE", "Conf", "Strat"];
  const xr = (v) => (v == null ? "—" : (v >= 0 ? "+" : "") + (+v).toFixed(2) + "R");
  const closedRows = (rs) => rs.map((t, i) => {
    const q = views[t.symbol] || {};
    const cp = t.current_price ?? t.exit_price ?? q.live_price ?? q.price;
    return (
      <tr key={i}>
        <td>{ts19(t.opened_at)}</td><td>{ts19(t.closed_at)}</td><td>{t.symbol}</td><td>{t.side}</td><td>{t.volume}</td>
        <td>{t.entry_price ?? "—"}</td><td>{cp ?? "—"}</td><td>{t.tp ?? t.take_profit ?? "—"}</td><td>{t.sl ?? t.stop_loss ?? "—"}</td>
        <td className={t.pnl >= 0 ? "pos-txt" : "neg-txt"}>{t.pnl != null ? signed(t.pnl) : "—"}</td>
        <td className="pos-txt">{xr(t.mfe_r)}</td><td className="neg-txt">{xr(t.mae_r)}</td>
        <td>{t.confidence != null ? Math.round(t.confidence * 100) + "%" : "—"}</td><td>{t.strategy || "—"}</td>
      </tr>
    );
  });

  return (
    <div className="page-pad stack">
      <div className="flex-row-between">
        <h2 className="sec" style={{ marginBottom: 0 }}>Open Positions</h2>
        <button className="btn-ghost" onClick={closeAll}>Close All</button>
      </div>
      <Card>
        <TradeSection title="Real" headers={openHeaders} rows={openRows(om.real)} empty="No real open trades." />
        <TradeSection title="Shadow" headers={openHeaders} rows={openRows(om.shadow)} empty="No shadow open trades." />
      </Card>

      <h2 className="sec">Closed Trades</h2>
      <Card>
        {closed.error ? <Empty>Could not load trade history.</Empty> : (
          <>
            <TradeSection title="Real" headers={closedHeaders} rows={closedRows(cm.real)} empty="No real closed trades." />
            <TradeSection title="Shadow" headers={closedHeaders} rows={closedRows(cm.shadow)} empty="No shadow closed trades." />
          </>
        )}
      </Card>
    </div>
  );
}
