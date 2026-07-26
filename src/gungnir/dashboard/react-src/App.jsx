import React, { useState, useEffect, useCallback, useRef } from "react";
import { usd, signed, cx } from "./format.js";
import { api, post } from "./api.js";

import Overview from "./tabs/Overview.jsx";
import Markets from "./tabs/Markets.jsx";
import Strategies from "./tabs/Strategies.jsx";
import Learning from "./tabs/Learning.jsx";
import Signals from "./tabs/Signals.jsx";
import Trades from "./tabs/Trades.jsx";
import Reports from "./tabs/Reports.jsx";
import Backtest from "./tabs/Backtest.jsx";
import Settings from "./tabs/Settings.jsx";

const NAV = [
  ["overview", "OVR", "Overview", <><rect x="2" y="4" width="5" height="16" /><rect x="9" y="8" width="5" height="12" /><rect x="16" y="6" width="5" height="14" /></>],
  ["markets", "MKT", "Markets", <polyline points="2 20 6 12 10 16 14 8 22 4" />],
  ["strategies", "STR", "Strategies", <><circle cx="6" cy="6" r="2" fill="currentColor" stroke="none" /><circle cx="18" cy="6" r="2" fill="currentColor" stroke="none" /><circle cx="12" cy="16" r="2" fill="currentColor" stroke="none" /><line x1="6" y1="8" x2="12" y2="14" /><line x1="18" y1="8" x2="12" y2="14" /></>],
  ["learning", "LRN", "Learning", <><path d="M4 5 L12 2 L20 5 L20 10 C20 15 12 20 12 20 C12 20 4 15 4 10 Z" /><line x1="12" y1="11" x2="12" y2="16" /></>],
  ["signals", "SIG", "Signals", <><line x1="2" y1="12" x2="22" y2="12" /><polyline points="6 5 2 12 6 19" /><polyline points="18 5 22 12 18 19" /></>],
  ["trades", "TRD", "Trades", <><rect x="3" y="5" width="18" height="14" rx="1" /><line x1="3" y1="10" x2="21" y2="10" /><line x1="8" y1="14" x2="16" y2="14" /></>],
  ["reports", "RPT", "Reports", <><rect x="4" y="3" width="16" height="18" rx="1" /><line x1="8" y1="8" x2="16" y2="8" /><line x1="8" y1="12" x2="16" y2="12" /><line x1="8" y1="16" x2="13" y2="16" /></>],
  ["backtest", "BT", "Backtest", <><circle cx="6" cy="6" r="3" /><path d="M18 3 Q21 6 18 9" /><polyline points="4 18 4 20 22 20" /><line x1="8" y1="16" x2="8" y2="20" /><line x1="16" y1="16" x2="16" y2="20" /></>],
  ["settings", "SET", "Settings", <><circle cx="12" cy="12" r="4" /><line x1="12" y1="8" x2="12" y2="10" /><line x1="12" y1="14" x2="12" y2="16" /></>],
];
const TITLES = Object.fromEntries(NAV.map(([id, , title]) => [id, title]));
// Tabs with editable forms or heavy aggregation load once on switch, not on
// the 5s tick — matches the production dashboard's NO_POLL set exactly, so
// a user mid-edit in Settings never gets their inputs clobbered by a refresh.
const NO_POLL = new Set(["settings", "backtest", "reports"]);

function Sidebar({ active, onTab }) {
  return (
    <div className="sidebar">
      <div className="logo-area">O</div>
      <nav>
        {NAV.map(([id, abbr, title, icon]) => (
          <button key={id} className={cx(active === id && "active")} title={title} onClick={() => onTab(id)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">{icon}</svg>
            <span>{abbr}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function Freshness({ ts }) {
  const [, setTick] = useState(0);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 1000); return () => clearInterval(id); }, []);
  if (!ts) return <span className="data-fresh bad">no data</span>;
  const age = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  const cls = age < 20 ? "good" : age < 90 ? "warn" : "bad";
  const label = age < 2 ? "● live" : "● updated " + (age < 60 ? Math.round(age) + "s" : Math.round(age / 60) + "m") + " ago";
  return <span className={cx("data-fresh", cls)}>{label}</span>;
}

function Topbar({ tab, status, connOk, reload }) {
  const s = status || {};
  const acc = s.account || {}, pnl = s.pnl || {}, broker = s.broker || {};
  const shp = s.pnl_shadow || {};
  const equity = acc.equity ?? s.equity ?? 0;
  const daily = (s.day_start_equity != null && s.day_start_equity > 0) ? equity - s.day_start_equity : null;
  const paper = s.paper_mode ?? ((s.risk_settings || {}).PAPER_TRADE ?? (s.mode !== "live"));
  const agentOn = s.agent_enabled ?? !s.paused;
  const killed = !!(s.kill_switch ?? s.killed);
  const gate = !!s.offline_gate;

  const toggleAgent = () => post("/api/agent/toggle", { enabled: !agentOn }).then(reload);
  const toggleGate = () => post("/api/offline_gate/toggle", { enabled: !gate }).then(reload);
  const toggleKill = () => post("/api/kill", { engage: !killed }).then(reload);

  return (
    <>
      {killed && <div className="kill-banner on">⛔ KILL SWITCH ENGAGED — NO NEW ORDERS. Tap KILLED in the header to disengage.</div>}
      <div className="topbar">
        <div className="title">{TITLES[tab] || "Overview"}</div>
        <div className="right-section">
          <div className="metrics">
            <div className="metric-item"><div className="metric-label">Equity</div><div className="metric-value bold">{usd(equity)}</div></div>
            <div className="divider" />
            <div className="metric-group">
              <div className="metric-label">Real / Live</div>
              <div className="mg-rows">
                <div className="mg-row"><span className="mg-k">Closed</span><span className={cx("mg-v", (pnl.closed ?? s.closed_pl) >= 0 ? "pos" : "neg")}>{signed(pnl.closed ?? s.closed_pl)}</span></div>
                <div className="mg-row"><span className="mg-k">Broker P/L</span><span className={cx("mg-v", (broker.broker_running_pl ?? pnl.running ?? s.running_pl) >= 0 ? "pos" : "neg")}>{signed(broker.broker_running_pl ?? pnl.running ?? s.running_pl)}</span></div>
              </div>
            </div>
            <div className="metric-group">
              <div className="metric-label shadow">Shadow</div>
              <div className="mg-rows">
                <div className="mg-row"><span className="mg-k">Closed</span><span className={cx("mg-v", (shp.closed ?? 0) >= 0 ? "pos" : "neg")}>{signed(shp.closed)}</span></div>
                <div className="mg-row"><span className="mg-k">Open</span><span className={cx("mg-v", (shp.running ?? 0) >= 0 ? "pos" : "neg")}>{signed(shp.running)}</span></div>
              </div>
            </div>
            <div className="divider" />
            <div className="metric-item"><div className="metric-label">Daily P/L</div><div className={cx("metric-value", daily >= 0 ? "pos" : "neg")}>{daily == null ? "—" : signed(daily)}</div></div>
          </div>
          <div className="divider" />
          <div className={cx("conn-dot", connOk ? "ok" : "bad")} title="Connection to agent" />
          <Freshness ts={s.ts} />
          <div className="toggle-group">
            <button className={cx("toggle-btn", "active", !paper && "danger")} title={paper ? (s.live_block_reason || "Paper execution is active") : "Live execution is active"}>{paper ? "PAPER" : "LIVE"}</button>
            <button className={cx("toggle-btn", agentOn && "active", !agentOn && "danger")} onClick={toggleAgent} title="Toggle Agent On/Off">{agentOn ? "AGENT ON" : "AGENT OFF"}</button>
            <button className={cx("toggle-btn", gate && "active")} onClick={toggleGate} style={{ opacity: s.offline_policy_loaded ? 1 : 0.45 }}
              title={s.offline_policy_loaded ? "Offline RL veto — blocks signals the offline policy disagrees with (veto-only)" : "No offline policy loaded — train one and set rl.offline_advisory"}>
              {gate ? "RL VETO ON" : "RL VETO"}
            </button>
            <button className={cx("toggle-btn", killed && "active", killed && "danger")} onClick={toggleKill} title="Hard stop: no new orders leave until disengaged. Independent of pause and the risk breakers.">{killed ? "KILLED" : "KILL"}</button>
          </div>
        </div>
      </div>
    </>
  );
}

export default function App() {
  const [tab, setTab] = useState("overview");
  const [status, setStatus] = useState(null);
  const [connOk, setConnOk] = useState(true);
  const timer = useRef(null);

  const loadStatus = useCallback(async () => {
    try { const s = await api("/api/status"); setStatus(s); setConnOk(true); }
    catch (e) { setConnOk(false); }
  }, []);

  useEffect(() => {
    loadStatus();
    timer.current = setInterval(() => { if (!NO_POLL.has(tab)) loadStatus(); }, 5000);
    return () => clearInterval(timer.current);
  }, [loadStatus, tab]);

  return (
    <div className="shell">
      <Sidebar active={tab} onTab={setTab} />
      <Topbar tab={tab} status={status} connOk={connOk} reload={loadStatus} />
      <main className="main">
        {tab === "overview" && <Overview status={status} reload={loadStatus} />}
        {tab === "markets" && <Markets />}
        {tab === "strategies" && <Strategies />}
        {tab === "learning" && <Learning />}
        {tab === "signals" && <Signals />}
        {tab === "trades" && <Trades status={status} reload={loadStatus} />}
        {tab === "reports" && <Reports />}
        {tab === "backtest" && <Backtest />}
        {tab === "settings" && <Settings status={status} reload={loadStatus} />}
      </main>
    </div>
  );
}
