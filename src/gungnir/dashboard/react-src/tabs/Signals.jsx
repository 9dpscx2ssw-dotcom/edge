import React from "react";
import { Card, usePoll, Empty, SortTable } from "../components.jsx";
import { signed, cx } from "../format.js";

function Box({ title, b }) {
  return (
    <Card title={title}>
      <p>Win rate: <strong>{b.win_rate || 0}%</strong></p>
      <p>W / L: <span className="wl"><span className="pos-txt">{b.wins || 0}</span> / <span className="neg-txt">{b.losses || 0}</span></span> · {b.count || 0} graded</p>
      <p>P&amp;L: <span style={{ color: (b.pnl || 0) >= 0 ? "var(--good)" : "var(--bad)" }}>{signed(b.pnl || 0)}</span> · avg {b.avg_return || 0}</p>
    </Card>
  );
}

const ts19 = (s) => (s || "").slice(0, 19).replace("T", " ") || "—";

export default function Signals() {
  const { data } = usePoll("/api/signals", { intervalMs: 5000 });
  const d = data || {};
  const byStrat = Object.entries(d.by_strategy || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
  const rows = d.recent || [];

  const px = (v) => (v == null ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: 4 }));
  const lot = (v) => (v == null ? "—" : (+v).toFixed(4));
  const result = (r) => r.won == null ? (r.executed ? <span className="faint">open</span> : "") : <span className={cx("result-tag", r.won ? "win" : "loss")}>{r.won ? "WIN" : "LOSS"}</span>;
  const sent = (v) => v == null ? "—" : <span className={v > 0 ? "pos-txt" : v < 0 ? "neg-txt" : "faint"}>{v > 0 ? "+" : ""}{(+v).toFixed(2)}</span>;
  const rlp = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
  const gate = (r) => r.rejection_reason ? <span className="gate-reason" title={JSON.stringify(r.rejection_detail || {})}>{r.rejection_reason}</span> : "—";

  return (
    <div className="page-pad stack">
      <div className="grid-3col">
        <Box title="Overall" b={d.overall || {}} />
        <Box title="Executed (Real)" b={d.executed || {}} />
        <Box title="Shadow" b={d.shadow || {}} />
      </div>

      <h2 className="sec">By strategy</h2>
      <Card>
        <div className="tscroll">
          <SortTable
            columns={[
              { key: "name", label: "Strategy", left: true },
              { key: "win_rate", label: "Win rate", render: (x) => (x.b.win_rate || 0) + "%" },
              { key: "wins", label: "Wins", render: (x) => <span className="pos-txt">{x.b.wins || 0}</span>, sortValue: (x) => x.b.wins },
              { key: "losses", label: "Losses", render: (x) => <span className="neg-txt">{x.b.losses || 0}</span>, sortValue: (x) => x.b.losses },
              { key: "pnl", label: "P&L", render: (x) => <span className={(x.b.pnl || 0) >= 0 ? "pos-txt" : "neg-txt"}>{signed(x.b.pnl || 0)}</span>, sortValue: (x) => x.b.pnl },
            ]}
            rows={byStrat.map(([name, b]) => ({ name: name || "—", b }))}
            rowKey={(x) => x.name}
            initialSort={{ key: "wins", dir: -1 }}
          />
        </div>
      </Card>

      <h2 className="sec">Recent signals</h2>
      <Card>
        <div className="tscroll">
          <table>
            <thead><tr><th className="left">Time</th><th className="left">Symbol</th><th className="left">Dir</th><th>Strat</th><th>Conf</th><th>Sent</th><th>RL</th><th>Lot</th><th>TP</th><th>SL</th><th className="left">Gate</th><th>Result</th></tr></thead>
            <tbody>
              {!rows.length && <tr><td className="left faint" colSpan={12}>No signals yet.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="left tabular faint">{ts19(r.graded_at)}</td>
                  <td className="left">{r.symbol || ""}</td>
                  <td className="left">{r.direction || ""}</td>
                  <td>{r.strategy ? "S" + r.strategy : "—"}</td>
                  <td>{r.confidence || 0}%</td>
                  <td>{sent(r.sentiment)}</td>
                  <td>{rlp(r.rl_p)}</td>
                  <td>{lot(r.lot)}</td>
                  <td>{px(r.take_profit)}</td>
                  <td>{px(r.stop_loss)}</td>
                  <td className="left">{gate(r)}</td>
                  <td>{result(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
