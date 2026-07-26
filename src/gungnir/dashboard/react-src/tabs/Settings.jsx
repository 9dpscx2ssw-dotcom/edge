import React, { useEffect, useState, useCallback } from "react";
import { Card } from "../components.jsx";
import { api, post } from "../api.js";

const num = (v) => (v == null ? "" : v);
const FIELD = (label, children) => <div className="ctrl"><label>{label}</label>{children}</div>;

function flatten(o, pre = "") {
  const out = [];
  for (const k in (o || {})) {
    const v = o[k];
    if (v && typeof v === "object" && !Array.isArray(v)) out.push(...flatten(v, pre + k + "."));
    else out.push([pre + k, Array.isArray(v) ? v.length + " items" : String(v)]);
  }
  return out;
}

export default function Settings({ status, reload }) {
  const [d, setD] = useState(null);
  const [runtime, setRuntime] = useState({ dryRun: false, paperTrade: true });
  const [risk, setRisk] = useState({});
  const [filters, setFilters] = useState({});
  const [reflection, setReflection] = useState("bayesian");
  const [busy, setBusy] = useState({});

  const load = useCallback(async () => {
    const dd = await api("/api/settings");
    setD(dd);
    const rt = dd.runtime || {};
    const ctrl = dd.control || {};
    setRuntime({ dryRun: (ctrl.runtime || {}).dry_run ?? !!rt.dry_run, paperTrade: (ctrl.risk_settings || {}).PAPER_TRADE ?? !!rt.paper_mode });
    const rs = ctrl.risk_settings || {}, cfgRisk = (dd.config || {}).risk || {}, cfgCosts = (dd.config || {}).costs || {};
    setRisk({
      risk: num(rs.account_risk_per_trade ?? cfgRisk.account_risk_per_trade),
      volTarget: num(rs.vol_target_annual ?? cfgRisk.vol_target_annual),
      maxGross: num(rs.max_portfolio_exposure ?? cfgRisk.max_portfolio_exposure),
      maxAsset: num(rs.max_per_asset_exposure ?? cfgRisk.max_per_asset_exposure),
      maxOpen: num(rs.max_open_positions ?? cfgRisk.max_open_positions),
      dailyLoss: num(rs.daily_loss_limit ?? cfgRisk.max_daily_loss),
      minLot: num(rs.min_lot ?? cfgRisk.min_lot),
      maxLot: num(rs.max_lot ?? cfgRisk.max_lot),
      minConf: num(rs.min_confidence ?? cfgRisk.min_confidence),
      leverage: num(rs.leverage ?? cfgRisk.leverage),
      levMargin: num(rs.leverage_safety_margin ?? cfgRisk.leverage_safety_margin),
      startBal: num(rs.starting_balance),
      spread: num(rs.spread_bps ?? cfgCosts.spread_bps),
      comm: num(rs.commission_bps ?? cfgCosts.commission_bps),
      slip: num(rs.slippage_bps ?? cfgCosts.slippage_bps),
      llmProvider: ctrl.llm_provider || (dd.config || {}).llm?.provider || "none",
    });
    const flt = { ...(dd.config || {}).filters, ...ctrl.filters };
    setFilters({
      trend: !!flt.trend, volatility: !!flt.volatility, volume: !!flt.volume, session: !!flt.session,
      spread: !!flt.spread, regime: !!flt.regime, noise: !!flt.noise, timeframe: !!flt.timeframe,
      regimeEnforce: flt.regime_mode === "enforce", noiseEnforce: flt.noise_mode === "enforce",
      volMin: num(flt.vol_min), volMax: num(flt.vol_max), volR: num(flt.min_volume_ratio),
      maxSpread: num(flt.max_spread_bps), adx: num(flt.adx_trend),
      noiseMin: num(flt.noise_min_ema_atr), noiseMax: num(flt.noise_max_ema_atr), minTf: num(flt.min_timeframe_minutes),
    });
    const lrn = ctrl.learning || (dd.config || {}).learning || {};
    setReflection(lrn.reflection_mode ?? "bayesian");
  }, []);

  useEffect(() => { load(); }, [load]);

  const flash = (key, ok) => { setBusy((b) => ({ ...b, [key]: ok ? "Saved ✓" : "Failed" })); setTimeout(() => setBusy((b) => ({ ...b, [key]: null })), 1500); };

  const saveRuntime = async () => {
    try { await post("/api/settings/runtime", { dry_run: runtime.dryRun, paper_trade: runtime.paperTrade }); flash("runtime", true); await load(); await reload(); }
    catch (e) { flash("runtime", false); }
  };
  const saveRisk = async () => {
    const body = {};
    const f = (v, key) => { const x = parseFloat(v); if (!Number.isNaN(x)) body[key] = x; };
    f(risk.risk, "account_risk_per_trade"); const mo = parseInt(risk.maxOpen, 10); if (!Number.isNaN(mo)) body.max_open_positions = mo;
    f(risk.dailyLoss, "daily_loss_limit"); f(risk.minLot, "min_lot");
    const xl = parseFloat(risk.maxLot); body.max_lot = Number.isNaN(xl) ? null : xl;
    f(risk.minConf, "min_confidence"); f(risk.startBal, "starting_balance");
    f(risk.spread, "spread_bps"); f(risk.comm, "commission_bps"); f(risk.slip, "slippage_bps");
    try { await post("/api/risk", body); flash("risk", true); await load(); } catch (e) { flash("risk", false); }
  };
  const saveFilters = async () => {
    const body = {};
    ["trend", "volatility", "volume", "session", "spread", "regime", "noise", "timeframe"].forEach((k) => { body[k] = !!filters[k]; });
    body.regime_mode = filters.regimeEnforce ? "enforce" : "shadow";
    body.noise_mode = filters.noiseEnforce ? "enforce" : "observe";
    const n = (v, key) => { const x = parseFloat(v); if (!Number.isNaN(x)) body[key] = x; };
    n(filters.volMin, "vol_min"); n(filters.volMax, "vol_max"); n(filters.volR, "min_volume_ratio");
    n(filters.maxSpread, "max_spread_bps"); n(filters.adx, "adx_trend");
    n(filters.noiseMin, "noise_min_ema_atr"); n(filters.noiseMax, "noise_max_ema_atr"); n(filters.minTf, "min_timeframe_minutes");
    try { await post("/api/filters", body); flash("filters", true); await load(); } catch (e) { flash("filters", false); }
  };
  const saveLearning = async () => {
    try { await post("/api/learning", { reflection_mode: reflection }); flash("learning", true); await load(); } catch (e) { flash("learning", false); }
  };

  if (!d) return <div className="page-pad"><p className="faint">Loading settings…</p></div>;
  const rt = d.runtime || {};
  const rj = (status?.filters || {}).rejects || {};
  const consensusKeys = ["consensus_conflict", "consensus_risk", "consensus_compliance"];
  const rjKeys = [...new Set([...Object.keys(rj), ...consensusKeys])];
  const configFlat = flatten(d.config || {});
  const controlFlat = flatten(d.control || {});
  const effectiveRows = [
    ["Effective mode", rt.paper_mode ? "PAPER / DRY-RUN" : "LIVE"],
    ["Live authorization", rt.live_allowed ? "AUTHORIZED" : "BLOCKED"],
    ["Effective dry run", rt.dry_run ? "ON" : "OFF"],
    ["Agent", rt.agent_enabled ? "ON" : "OFF"],
    ["Kill switch", rt.kill_switch ? "ENGAGED" : "DISENGAGED"],
    ["Live block reason", rt.live_block_reason || "—"],
  ];

  return (
    <div className="page-pad stack">
      <h2 className="sec">Runtime Safety</h2>
      <Card>
        <div className="settings-grid">
          <div className="kv"><div className="k">Execution mode</div><div className="v">{rt.paper_mode ? "PAPER / DRY-RUN" : "LIVE"}</div></div>
          <div className="kv"><div className="k">Live authorization</div><div className="v" style={{ color: rt.live_allowed ? "var(--good)" : "var(--bad)" }}>{rt.live_allowed ? "AUTHORIZED" : "BLOCKED"}</div></div>
          <div className="kv"><div className="k">Paper / shadow trading</div><label className="switch"><input type="checkbox" checked={runtime.paperTrade} onChange={(e) => setRuntime((r) => ({ ...r, paperTrade: e.target.checked }))} /><span className="slider" /></label></div>
          <div className="kv"><div className="k">Dry run</div><label className="switch"><input type="checkbox" checked={runtime.dryRun} onChange={(e) => setRuntime((r) => ({ ...r, dryRun: e.target.checked }))} /><span className="slider" /></label></div>
          <div className="kv"><div className="k">Agent</div><div className="v">{rt.agent_enabled ? "ON" : "OFF"}</div></div>
          <div className="kv"><div className="k">Kill switch</div><div className="v">{rt.kill_switch ? "ENGAGED" : "DISENGAGED"}</div></div>
        </div>
        {rt.live_block_reason && <div className="kv warn-note">{rt.live_block_reason}</div>}
        <button className="btn primary" style={{ marginTop: 12 }} onClick={saveRuntime}>{busy.runtime || "Save Execution Settings"}</button>
      </Card>

      <h2 className="sec">Risk Settings</h2>
      <Card>
        <div className="controls">
          {FIELD("LLM provider", <select value={risk.llmProvider} onChange={(e) => setRisk((r) => ({ ...r, llmProvider: e.target.value }))}>
            <option value="ollama">Ollama</option><option value="anthropic">Anthropic</option><option value="codex">Codex</option><option value="none">Disabled</option>
          </select>)}
          {FIELD("Risk / trade", <input type="number" step="0.001" value={risk.risk} onChange={(e) => setRisk((r) => ({ ...r, risk: e.target.value }))} />)}
          {FIELD("Vol target", <input type="number" step="0.01" value={risk.volTarget} onChange={(e) => setRisk((r) => ({ ...r, volTarget: e.target.value }))} />)}
          {FIELD("Max gross exposure", <input type="number" step="0.1" value={risk.maxGross} onChange={(e) => setRisk((r) => ({ ...r, maxGross: e.target.value }))} />)}
          {FIELD("Max asset exposure", <input type="number" step="0.1" value={risk.maxAsset} onChange={(e) => setRisk((r) => ({ ...r, maxAsset: e.target.value }))} />)}
          {FIELD("Max open", <input type="number" value={risk.maxOpen} onChange={(e) => setRisk((r) => ({ ...r, maxOpen: e.target.value }))} />)}
          {FIELD("Daily loss limit", <input type="number" step="0.01" value={risk.dailyLoss} onChange={(e) => setRisk((r) => ({ ...r, dailyLoss: e.target.value }))} />)}
          {FIELD("Min lot size", <input type="number" step="0.001" placeholder="0" value={risk.minLot} onChange={(e) => setRisk((r) => ({ ...r, minLot: e.target.value }))} />)}
          {FIELD("Max lot size", <input type="number" step="0.001" placeholder="none" value={risk.maxLot} onChange={(e) => setRisk((r) => ({ ...r, maxLot: e.target.value }))} />)}
          {FIELD("Min confidence", <input type="number" step="0.01" min="0" max="1" placeholder="0.3" value={risk.minConf} onChange={(e) => setRisk((r) => ({ ...r, minConf: e.target.value }))} />)}
          {FIELD("Max leverage", <input type="number" step="0.1" min="0.1" value={risk.leverage} onChange={(e) => setRisk((r) => ({ ...r, leverage: e.target.value }))} />)}
          {FIELD("Leverage safety margin", <input type="number" step="0.01" min="0" max="0.99" value={risk.levMargin} onChange={(e) => setRisk((r) => ({ ...r, levMargin: e.target.value }))} />)}
          {FIELD("Starting balance", <input type="number" step="100" placeholder="10000" value={risk.startBal} onChange={(e) => setRisk((r) => ({ ...r, startBal: e.target.value }))} />)}
          {FIELD("Spread (bps)", <input type="number" step="0.1" placeholder="0" value={risk.spread} onChange={(e) => setRisk((r) => ({ ...r, spread: e.target.value }))} />)}
          {FIELD("Commission (bps)", <input type="number" step="0.1" placeholder="0" value={risk.comm} onChange={(e) => setRisk((r) => ({ ...r, comm: e.target.value }))} />)}
          {FIELD("Slippage (bps)", <input type="number" step="0.1" placeholder="0" value={risk.slip} onChange={(e) => setRisk((r) => ({ ...r, slip: e.target.value }))} />)}
          <button className="btn primary" onClick={saveRisk}>{busy.risk || "Save"}</button>
        </div>
      </Card>

      <h2 className="sec">Pre-Trade Filters <span className="sec-dim">veto-only context gates · toggle each</span></h2>
      <Card>
        <div className="filter-grid">
          {[["trend", "Trend"], ["volatility", "Volatility"], ["volume", "Volume"], ["session", "Session"], ["spread", "Spread"], ["regime", "Regime"]].map(([k, label]) => (
            <label className="flt-item" key={k}><span>{label}</span><label className="switch"><input type="checkbox" checked={!!filters[k]} onChange={(e) => setFilters((f) => ({ ...f, [k]: e.target.checked }))} /><span className="slider" /></label></label>
          ))}
          <label className="flt-item" title="When enabled, matching configured family × regime rules block entries. When disabled, matches are recorded as shadow observations only."><span>Enforce regime veto</span><label className="switch"><input type="checkbox" checked={filters.regimeEnforce} onChange={(e) => setFilters((f) => ({ ...f, regimeEnforce: e.target.checked }))} /><span className="slider" /></label></label>
          <label className="flt-item" title="No-trend-structure filter: skip entries where the fast/slow EMA spread is below the ATR threshold (chop / no established trend)."><span>Noise</span><label className="switch"><input type="checkbox" checked={filters.noise} onChange={(e) => setFilters((f) => ({ ...f, noise: e.target.checked }))} /><span className="slider" /></label></label>
          <label className="flt-item" title="When enabled, noise-flagged entries are blocked. When disabled, they are tagged only (observe)."><span>Enforce noise veto</span><label className="switch"><input type="checkbox" checked={filters.noiseEnforce} onChange={(e) => setFilters((f) => ({ ...f, noiseEnforce: e.target.checked }))} /><span className="slider" /></label></label>
          <label className="flt-item" title="Block signals from strategies whose timeframe is below the minute floor below."><span>Min timeframe</span><label className="switch"><input type="checkbox" checked={filters.timeframe} onChange={(e) => setFilters((f) => ({ ...f, timeframe: e.target.checked }))} /><span className="slider" /></label></label>
        </div>
        <div className="controls" style={{ marginTop: 14 }}>
          {FIELD("Vol floor (atr/px)", <input type="number" step="0.0001" value={filters.volMin} onChange={(e) => setFilters((f) => ({ ...f, volMin: e.target.value }))} />)}
          {FIELD("Vol ceiling", <input type="number" step="0.001" value={filters.volMax} onChange={(e) => setFilters((f) => ({ ...f, volMax: e.target.value }))} />)}
          {FIELD("Min volume ratio", <input type="number" step="0.1" value={filters.volR} onChange={(e) => setFilters((f) => ({ ...f, volR: e.target.value }))} />)}
          {FIELD("Max spread (bps)", <input type="number" step="0.1" value={filters.maxSpread} onChange={(e) => setFilters((f) => ({ ...f, maxSpread: e.target.value }))} />)}
          {FIELD("ADX trend thresh", <input type="number" step="1" value={filters.adx} onChange={(e) => setFilters((f) => ({ ...f, adx: e.target.value }))} />)}
          {FIELD("Noise min EMA/ATR", <input type="number" step="0.05" value={filters.noiseMin} onChange={(e) => setFilters((f) => ({ ...f, noiseMin: e.target.value }))} />)}
          {FIELD("Noise max EMA/ATR", <input type="number" step="0.05" value={filters.noiseMax} onChange={(e) => setFilters((f) => ({ ...f, noiseMax: e.target.value }))} />)}
          {FIELD("Min timeframe (min)", <input type="number" step="5" value={filters.minTf} onChange={(e) => setFilters((f) => ({ ...f, minTf: e.target.value }))} />)}
          <button className="btn primary" onClick={saveFilters}>{busy.filters || "Save Filters"}</button>
        </div>
        <div className="kv" style={{ marginTop: 10 }}><span className="k">Vetoed signals / blocked entries:</span> {rjKeys.map((k) => <span className="v inline-v" key={k}>{k} {rj[k] || 0}</span>)}</div>
      </Card>

      <h2 className="sec">Learning &amp; Optimization</h2>
      <Card>
        <div className="controls">
          {FIELD("Reflection Mode", <select value={reflection} onChange={(e) => setReflection(e.target.value)}>
            <option value="llm">LLM Mode (batch all strategies → 1 call/hour)</option>
            <option value="bayesian">Bayesian Mode (deterministic, 0 LLM calls)</option>
          </select>)}
          <button className="btn primary" onClick={saveLearning}>{busy.learning || "Save"}</button>
        </div>
      </Card>

      <h2 className="sec">Configuration &amp; Runtime</h2>
      <div className="settings-pair">
        <Card><h3 className="card-title-inline">Configuration <span className="tag">config.yaml</span></h3>
          <div className="kv-flat">{configFlat.map(([k, v]) => <div key={k}><span className="k">{k}:</span> <span className="v">{v}</span></div>)}</div>
        </Card>
        <Card><h3 className="card-title-inline">Runtime Settings <span className="tag">control.json</span></h3>
          <div className="runtime-summary">
            <div className="kv full"><span className="k">Effective safety state</span></div>
            {effectiveRows.map(([k, v]) => <div className="kv" key={k}><span className="k">{k}</span><span className="v">{v}</span></div>)}
            <div className="kv full" style={{ marginTop: 8 }}><span className="k">Persisted control.json</span></div>
            {controlFlat.length ? controlFlat.map(([k, v]) => <div className="kv" key={k}><span className="k">{k}</span><span className="v">{v}</span></div>) : <span>—</span>}
          </div>
        </Card>
      </div>

      <h2 className="sec">Available Strategies</h2>
      <Card><p>{(d.strategies_available || []).join(", ") || "—"}</p></Card>
    </div>
  );
}
