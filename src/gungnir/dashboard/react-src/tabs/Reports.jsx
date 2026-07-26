import React, { useEffect, useState } from "react";
import { Card, Empty, SortTable } from "../components.jsx";
import { Sparkline, EquityChart } from "../charts.jsx";
import { usd, signed, pctRaw } from "../format.js";
import { api } from "../api.js";

// A deliberately simplified Reports tab: the production dashboard's Reports
// tab is an elaborate bespoke analytics surface (donut charts, diverging
// instrument bars, a strategy scorecard heatmap). This port keeps the same
// real /api/performance data — KPIs, sparklines, equity curve, per-strategy
// and per-instrument breakdowns — without cloning every custom visual widget.
const KPI = ({ label, value, cls, spark, delta }) => (
  <div className="rp-kpi">
    <div className="rp-kpi-lbl">{label}</div>
    <div className={"rp-kpi-val " + (cls || "")}>{value}</div>
    {spark && spark.length > 1 && <Sparkline series={spark} height={30} />}
    {delta != null && <div className={"rp-kpi-delta " + (delta >= 0 ? "pos-txt" : "neg-txt")}>{delta >= 0 ? "+" : ""}{delta.toFixed(1)}% vs prior window</div>}
  </div>
);

export default function Reports() {
  const [data, setData] = useState(null);
  const [window_, setWindow] = useState("daily");
  const [error, setError] = useState(null);

  useEffect(() => { api("/api/performance").then(setData).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="page-pad"><Empty>Could not load performance data.</Empty></div>;
  if (!data) return <div className="page-pad"><p className="faint">Loading…</p></div>;

  const w = data[window_] || {};
  const delta = (data.deltas || {})[window_] || {};
  const sparks = w.sparks || {};
  const byStrat = Object.entries(w.by_strategy || {});
  const byInst = Object.entries(w.by_instrument || {});

  return (
    <div className="page-pad stack">
      <div className="rp-summary">
        <div className="rp-summary-lbl">Summary</div>
        <p>{data.summary || "—"}</p>
        {data.generated_at && <p className="faint small">generated {new Date(data.generated_at).toLocaleString()}</p>}
      </div>

      <div className="rp-seg">
        <button className={window_ === "daily" ? "active" : ""} onClick={() => setWindow("daily")}>Today</button>
        <button className={window_ === "weekly" ? "active" : ""} onClick={() => setWindow("weekly")}>Last 7 days</button>
      </div>

      <div className="rp-kpis">
        <KPI label="Trades" value={w.trades ?? 0} spark={sparks.trades} delta={delta.trades} />
        <KPI label="Win rate" value={pctRaw((w.win_rate || 0) / 100)} spark={sparks.win_rate} delta={delta.win_rate} />
        <KPI label="P&L" value={signed(w.pnl)} cls={(w.pnl || 0) >= 0 ? "pos-txt" : "neg-txt"} spark={sparks.pnl} delta={delta.pnl} />
        <KPI label="Expectancy" value={(w.expectancy ?? 0).toFixed(2)} />
        <KPI label="Profit factor" value={w.profit_factor == null ? "∞" : w.profit_factor.toFixed(2)} spark={sparks.profit_factor} delta={delta.profit_factor} />
        <KPI label="Sharpe" value={(w.sharpe ?? 0).toFixed(2)} />
      </div>

      <div className="grid-2col">
        <Card title="Equity curve">
          {w.equity_curve?.length ? <EquityChart real={w.equity_curve} shadow={[]} base={w.equity_curve[0]?.equity ?? 0} height={200} /> : <Empty>No closed trades in this window.</Empty>}
        </Card>
        <Card title="Real vs shadow">
          <div className="kv-grid">
            <span className="k">Real P&amp;L</span><span className="v">{signed(w.real_pnl)}</span>
            <span className="k">Shadow P&amp;L</span><span className="v">{signed(w.shadow_pnl)}</span>
            <span className="k">Gross win</span><span className="v pos-txt">{usd(w.gross_win)}</span>
            <span className="k">Gross loss</span><span className="v neg-txt">{usd(w.gross_loss)}</span>
            <span className="k">Max drawdown</span><span className="v">{(w.max_drawdown ?? 0).toFixed(1)}%</span>
            <span className="k">Avg confidence</span><span className="v">{w.avg_confidence != null ? Math.round(w.avg_confidence * 100) + "%" : "—"}</span>
          </div>
        </Card>
      </div>

      <h2 className="sec">By strategy</h2>
      <Card>
        <div className="tscroll">
          <SortTable
            columns={[
              { key: "name", label: "Strategy", left: true },
              { key: "trades", label: "Trades", render: (x) => x.b.trades ?? 0, sortValue: (x) => x.b.trades },
              { key: "win_rate", label: "Win %", render: (x) => (x.b.win_rate ?? 0) + "%", sortValue: (x) => x.b.win_rate },
              { key: "pnl", label: "P&L", render: (x) => <span className={(x.b.pnl || 0) >= 0 ? "pos-txt" : "neg-txt"}>{signed(x.b.pnl)}</span>, sortValue: (x) => x.b.pnl },
            ]}
            rows={byStrat.map(([name, b]) => ({ name, b }))}
            rowKey={(x) => x.name}
            initialSort={{ key: "pnl", dir: -1 }}
          />
        </div>
      </Card>

      <h2 className="sec">By instrument</h2>
      <Card>
        <div className="tscroll">
          <SortTable
            columns={[
              { key: "name", label: "Symbol", left: true },
              { key: "trades", label: "Trades", render: (x) => x.b.trades ?? 0, sortValue: (x) => x.b.trades },
              { key: "win_rate", label: "Win %", render: (x) => (x.b.win_rate ?? 0) + "%", sortValue: (x) => x.b.win_rate },
              { key: "pnl", label: "P&L", render: (x) => <span className={(x.b.pnl || 0) >= 0 ? "pos-txt" : "neg-txt"}>{signed(x.b.pnl)}</span>, sortValue: (x) => x.b.pnl },
            ]}
            rows={byInst.map(([name, b]) => ({ name, b }))}
            rowKey={(x) => x.name}
            initialSort={{ key: "pnl", dir: -1 }}
          />
        </div>
      </Card>
    </div>
  );
}
