import React, { useMemo } from "react";
import { Card, usePoll, Empty, SortTable } from "../components.jsx";
import { Sparkline } from "../charts.jsx";
import { cx } from "../format.js";

const RLMetric = ({ label, value, sub }) => (
  <div className="rl-metric"><div className="lbl">{label}</div><div className="val">{value}</div><div className="sub">{sub}</div></div>
);

export default function Learning() {
  const { data } = usePoll("/api/learning", { intervalMs: 5000 });
  const rl = data?.rl || {};
  const on = rl.enabled;
  const mode = rl.mode || (on ? "active" : "off");

  const cumReward = useMemo(() => {
    const rh = rl.reward_history || [];
    if (rh.length < 2) return null;
    let c = 0;
    return rh.map((r) => (c += r));
  }, [rl.reward_history]);

  // Two populations, shown separately so neither hides the other — matches the
  // production dashboard's fix: "recent" is the rolling window the rl-collapse
  // alert actually fires on; "lifetime" is warm-up-skewed and must never drive
  // the headline %.
  const warm = rl.warmup_remaining ?? 0;
  const ac = rl.action_counts || {};
  const take = ac.take || 0, skip = ac.skip || 0, lifetimeTot = take + skip || 1;
  const lifetimeTakePct = Math.round((take / lifetimeTot) * 100);
  const rtr = rl.recent_take_rate;
  const hasRecent = rtr != null;
  const recentTakePct = hasRecent ? Math.round(rtr * 100) : null;
  const recentSkipPct = hasRecent ? 100 - recentTakePct : null;
  const eps = rl.epsilon ?? 0;
  const epsPct = Math.max(0, Math.min(100, Math.round((1 - eps) * 100)));

  const adv = data?.advisory;
  const weights = useMemo(() => Object.values(data?.strategy_weights || {}).sort((a, b) => b.win_rate - a.win_rate), [data]);
  const events = data?.events || [];

  return (
    <div className="page-pad stack">
      <h2 className="sec">Reinforcement Learning {on ? <span className={cx("pill", mode === "warmup" ? "warmup" : "active")}>{mode}</span> : <span className="pill off">disabled</span>}</h2>

      {on ? (
        <>
          <div className="rl-cards">
            <RLMetric label="Updates" value={rl.updates ?? 0} sub="policy gradient steps" />
            <RLMetric label="States Learned" value={rl.states_learned ?? 0} sub="experience buffer" />
            <RLMetric label="Cumulative Reward" value={(+(rl.cumulative_reward ?? 0)).toFixed(2)} sub="risk-normalized" />
            <RLMetric label="Avg Reward" value={(+(rl.avg_reward ?? 0)).toFixed(4)} sub="per recent decision" />
            <RLMetric label="Exploration ε" value={(+eps).toFixed(3)} sub={eps > 0.2 ? "exploring" : "exploiting"} />
            <RLMetric label="Last P(take)" value={(rl.last_p_take ?? 0).toFixed(3)} sub="policy confidence" />
          </div>

          <div className="account-grid">
            <Card><h3 className="card-title-inline">Learning Progress</h3>
              <div className="metric-block"><div className="section-title">Warmup</div>
                <div className="reward-value">{warm > 0 ? warm + " trades remaining" : "complete — policy is gating signals"}</div></div>
              <div className="metric-block"><div className="section-title">Exploitation (1 − ε)</div>
                <div className="progress"><span style={{ width: epsPct + "%" }} /></div>
                <div className="reward-value" style={{ marginTop: 4 }}>{epsPct}% exploiting · {100 - epsPct}% exploring</div></div>
              <div className="metric-block"><div className="section-title">Action mix — recent (rolling, last ≤100 decisions)</div>
                {hasRecent ? (
                  <>
                    <div className="actbar"><div style={{ width: recentTakePct + "%", background: "var(--good)" }} /><div style={{ width: recentSkipPct + "%", background: "var(--text-muted)" }} /></div>
                    <div className="reward-value" style={{ marginTop: 4 }}>Take {recentTakePct}% · Skip {recentSkipPct}%</div>
                  </>
                ) : <div className="reward-value" style={{ marginTop: 4 }}>Not enough recent decisions yet</div>}
                <div className="reward-value lifetime-note">Lifetime (n={lifetimeTot}, warm-up-skewed): {lifetimeTakePct}% take · {100 - lifetimeTakePct}% skip</div>
              </div>
            </Card>
            <Card className="chart-card"><h3 className="card-title-inline">Reward History</h3>
              {cumReward ? <Sparkline series={cumReward} color={cumReward[cumReward.length - 1] >= 0 ? "var(--good)" : "var(--bad)"} height={180} /> : <Empty>No reward history yet.</Empty>}
            </Card>
          </div>
        </>
      ) : <Empty>RL not active.</Empty>}

      <h2 className="sec">Offline RL Advisory <span className="sec-dim">shadow — advisory vs realized, not traded</span></h2>
      {adv && adv.n_graded ? (
        <div className="rl-cards">
          <RLMetric label="Hit Rate" value={(adv.hit_rate * 100).toFixed(1) + "%"} sub={adv.n_graded + " graded calls"} />
          <RLMetric label="Cum. Shadow Return" value={(adv.cum_shadow_return * 100).toFixed(2) + "%"} sub="gross, if followed" />
          <RLMetric label="Calls" value={`${(adv.by_action || {}).LONG || 0}/${(adv.by_action || {}).SHORT || 0}/${(adv.by_action || {}).FLAT || 0}`} sub="long / short / flat" />
          <RLMetric label="Verdict" value={adv.hit_rate > 0.5 && adv.cum_shadow_return > 0 ? "edge?" : "no edge"} sub="needs sustained + real data" />
        </div>
      ) : <Card><p className="muted">No graded advisories yet (enable rl.offline_advisory with a trained policy).</p></Card>}

      <h2 className="sec">Per-Strategy Win Rate</h2>
      <Card>
        <div className="tscroll">
          <SortTable
            columns={[
              { key: "strategy", label: "Strategy", left: true },
              { key: "win_rate", label: "Win Rate", render: (x) => (x.win_rate * 100).toFixed(1) + "%" },
              { key: "wins", label: "Wins", render: (x) => <span className="pos-txt">{x.wins}</span> },
              { key: "trades", label: "Trades" },
            ]}
            rows={weights}
            rowKey={(x) => x.strategy}
            initialSort={{ key: "win_rate", dir: -1 }}
          />
        </div>
      </Card>

      <h2 className="sec">Learning Events</h2>
      <Card>{events.length ? events.map((e, i) => <p key={i} className="event-line">{typeof e === "object" ? JSON.stringify(e) : e}</p>) : <p>No learning events yet.</p>}</Card>
    </div>
  );
}
