import React, { useMemo } from "react";
import { Card, Badge, usePoll, Empty, useTicker } from "../components.jsx";
import { EquityChart } from "../charts.jsx";
import { usd, signed, cx, ageLabel, freshnessBand } from "../format.js";
import { post } from "../api.js";

/** Freshness chip: how long ago the strategy actually fired, ticking live.
 * Color band scales to the strategy's own timeframe (see freshnessBand). */
function SignalFreshness({ ts, timeframe }) {
  const now = useTicker(1000);
  if (!ts) return null;
  const ageMs = now - new Date(ts).getTime();
  if (ageMs < 0) return null;
  const band = freshnessBand(ageMs, timeframe);
  return (
    <span className={cx("freshness", band)}>
      <span className={cx("dot", band === "fresh" && "pulse")} />
      {ageLabel(ageMs)}
    </span>
  );
}

/** Reason chips parsed from Signal.rationale (semicolon-separated condition
 * clauses, e.g. "EMA9↑EMA21; close>EMA55; ADX>25"). The first clause is the
 * actual trigger (the crossover/threshold cross) and gets the accent chip;
 * the rest are confirming conditions. Strategies that don't populate a
 * rationale yet fall back to an honest note rather than a fabricated one. */
function SignalReasons({ rationale }) {
  const clauses = (rationale || "").split(";").map((c) => c.trim()).filter(Boolean);
  if (!clauses.length) return <div className="reason-none">no rationale recorded for this strategy</div>;
  return (
    <div className="reason-row">
      {clauses.map((c, i) => <span key={i} className={cx("reason-chip", i === 0 && "trigger")}>{c}</span>)}
    </div>
  );
}

function ConsensusStrip({ views }) {
  const rows = useMemo(() => Object.entries(views || {})
    .filter(([, v]) => v && v.consensus)
    .map(([sym, v]) => ({ sym, ...v.consensus }))
    .sort((a, b) => Math.abs(b.score || 0) - Math.abs(a.score || 0)), [views]);
  if (!rows.length) return null;
  return (
    <>
      <h2 className="sec">Consensus <span className="sec-dim">one account decision per symbol · weighted vote (+buy / −sell)</span></h2>
      <Card><div className="cons-grid">
        {rows.map((r) => {
          const sc = +r.score || 0, dir = sc >= 0 ? "pos" : "neg", w = Math.min(50, Math.abs(sc) * 50);
          const opp = Math.round((r.opposing || 0) * 100);
          const act = (r.action || "none").toLowerCase();
          const dg = r.diagnostics || {};
          const raw = Number.isFinite(+dg.raw_score) ? (+dg.raw_score).toFixed(2) : "—";
          const hz = Object.entries(dg.horizons || {}).map(([k, v]) => `${k} ${(+v).toFixed(2)}`).join(" · ");
          return (
            <div className="cons-chip" key={r.sym}>
              <div className="top"><span className="sym">{r.sym}</span><span className={cx("cons-act", act)}>{act}</span></div>
              <div className="cons-meter"><div className="z" />
                <div className="fill" style={sc >= 0 ? { left: "50%", width: w + "%", background: "var(--good)" } : { right: "50%", width: w + "%", background: "var(--bad)" }} />
              </div>
              <div className="row">
                <span>score <b className={cx("cons-score", dir)}>{sc >= 0 ? "+" : ""}{sc.toFixed(2)}</b></span>
                <span>raw <b>{raw}</b></span>
                <span>opp <b style={opp >= 35 ? { color: "var(--bad)" } : undefined}>{opp}%</b></span>
                <span><b>{r.stances || 0}</b> <span className="faint">votes</span></span>
              </div>
              {hz && <div className="cons-horizons">horizons: {hz}</div>}
            </div>
          );
        })}
      </div></Card>
    </>
  );
}

export default function Overview({ status, reload }) {
  const eq = usePoll("/api/equity", { intervalMs: 15000 });

  if (!status) return <div className="page-pad"><Empty>Loading overview…</Empty></div>;
  const s = status;
  const acc = s.account || {}, pnl = s.pnl || {}, exe = s.execution || {};
  const equity = acc.equity ?? s.equity ?? 0;
  const broker = s.broker || {};
  const shp = s.pnl_shadow || {};
  const rl = s.rl || {};
  const bt = (s.signal || {}).best_trade || {};
  const dir = bt.direction || "HOLD";
  const conf = Math.round(bt.confidence ?? 0);
  const view = (s.views || {})[bt.symbol] || {};
  const px = view.live_price ?? view.price;
  const hasSoft = view.sentiment_score != null || view.prediction_conf != null || bt.rl_confidence != null;

  const eqData = eq.data;
  const hasEquity = eqData && (eqData.real?.length || eqData.shadow?.length);

  return (
    <div className="page-pad stack">
      <div className="ov-grid">
        <Card title={null}>
          <h3 className="card-title-inline">Account &amp; P&amp;L</h3>
          <div className="acct-head">
            <div className="acct-equity">
              <div className="metric-label">Current Equity</div>
              <span className="equity-big">{usd(equity)}</span>
              <div className="balance-bar" />
              <div className="balance-text">Balance: {usd(acc.balance ?? s.balance)}</div>
            </div>
            <div className="acct-pnl">
              <div className="metric-label">Total P&amp;L (Today)</div>
              <div className="pnl-row"><span className="k">Broker P/L</span><span className={cx("v", (broker.broker_running_pl ?? pnl.running ?? s.running_pl) >= 0 ? "pos" : "neg")}>{signed(broker.broker_running_pl ?? pnl.running ?? s.running_pl)}</span></div>
              <div className="pnl-row"><span className="k">Closed</span><span className={cx("v", (pnl.closed ?? s.closed_pl) >= 0 ? "pos" : "neg")}>{signed(pnl.closed ?? s.closed_pl)}</span></div>
              <div className="pnl-row"><span className="k">Shadow Open P/L</span><span className={cx("v", (shp.running ?? 0) >= 0 ? "pos" : "neg")}>{signed(shp.running)}</span></div>
            </div>
          </div>
          <hr className="hair" />
          <div className="execution-block">
            <div className="section-title-row"><span>Execution</span>
              <button className="btn-ghost" onClick={() => post("/api/shadow/reset").then(reload)} title="Clear shadow trading history and equity">Reset Shadow</button>
            </div>
            <div className="exec-items">
              <div className="exec-item">Real: <strong>{exe.open_trades ?? 0}</strong> open / {exe.paper_trade_count ?? (s.trade_counts || {}).real ?? 0} total</div>
              <div className="exec-item">Shadow: <strong>{exe.shadow_open_trades ?? 0}</strong> open / {exe.shadow_trade_count ?? (s.trade_counts || {}).shadow ?? 0} total</div>
            </div>
          </div>
          <div className="rl-reward-block">
            <div className="section-title-row"><span>RL Reward</span>
              <button className="btn-ghost" onClick={() => { if (window.confirm("Reset RL policy to zero? This restarts learning from scratch.")) post("/api/rl/reset").then(reload); }} title="Reset RL policy to zero">Reset RL</button>
            </div>
            <div className="reward-value">{(rl.updates ?? 0) + " updates"}{rl.reward != null ? " · reward " + (+rl.reward).toFixed(3) : ""}</div>
          </div>
        </Card>

        <div className="ov-stack">
          <Card className="chart-card">
            <div className="legend chart-legend"><span className="lg"><span className="swatch" style={{ background: "var(--good)" }} />Real</span><span className="lg"><span className="swatch dash" />Shadow</span></div>
            {hasEquity ? <EquityChart real={eqData.real} shadow={eqData.shadow} base={eqData.base} /> : <Empty>No closed trades yet — equity curve will appear here.</Empty>}
          </Card>
          <Card className="signal-card">
            <div className="signal-content">
              <div className="confidence-circle"><div className="confidence-text">{conf}%<br /><span>CONF</span></div></div>
              <div className="signal-info">
                <div className={cx("signal-badge", dir === "BUY" && "buy", dir === "SELL" && "sell")}>{dir}</div>
                <div className="signal-status">
                  {bt.symbol ? <>{dir} {bt.symbol}{bt.strategy_name ? " · " + bt.strategy_name : ""}{px != null ? " @ " + px : ""}</> : "No active signal"}
                </div>
                {bt.symbol ? (
                  <>
                    <div className="signal-meta"><SignalFreshness ts={bt.ts} timeframe={bt.timeframe} /></div>
                    <SignalReasons rationale={(s.signal || {}).analysis} />
                  </>
                ) : (
                  <div className="signal-waiting">Waiting for the agent…</div>
                )}
                {hasSoft && (
                  <div className="signal-soft">
                    <div className="signal-soft-grid">
                      <div><span className="soft-lbl magenta">Sentiment</span><br /><span className="soft-val">{view.sentiment_score != null ? (view.sentiment_score > 0 ? "+" : "") + view.sentiment_score.toFixed(2) : "—"}</span></div>
                      <div><span className="soft-lbl blue">Prediction</span><br /><span className="soft-val">{view.prediction_conf != null ? (view.prediction_conf * 100).toFixed(0) + "%" : "—"}</span></div>
                      <div><span className="soft-lbl purple">RL Score</span><br /><span className="soft-val">{bt.rl_confidence != null ? Math.round(bt.rl_confidence * 100) + "%" : "—"}</span></div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>
      </div>

      <ConsensusStrip views={s.views} />
    </div>
  );
}
