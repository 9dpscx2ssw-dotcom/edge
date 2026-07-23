"""SQLite persistence for trades, signals, and learning events.

SQLite keeps the homelab footprint near zero. Swap the connection for
TimescaleDB/Postgres later if you start storing tick-level history.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..data.models import Side, Signal, Trade

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    volume      REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price  REAL,
    pnl         REAL,
    strategy    TEXT,
    mode        TEXT DEFAULT 'real',   -- real | shadow
    opened_at   TEXT NOT NULL,
    closed_at   TEXT,
    context     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode);

-- Append-only order/fill/reconciliation ledger. Trade rows remain the compact
-- performance journal; these tables preserve execution lineage without rewriting history.
CREATE TABLE IF NOT EXISTS order_intents (
    client_id TEXT PRIMARY KEY, signal_id TEXT, ts TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, intended_size REAL NOT NULL, mode TEXT NOT NULL,
    decision_price REAL, cost_model TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, event_type TEXT NOT NULL,
    ts TEXT NOT NULL, broker_id TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_events_client ON execution_events(client_id, ts);
CREATE TABLE IF NOT EXISTS reconciliation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, ts TEXT NOT NULL,
    source TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reconciliation_events_client ON reconciliation_events(client_id, ts);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    conviction  REAL NOT NULL,
    price       REAL,
    disposition TEXT NOT NULL,          -- real | shadow | rejected_risk | rejected_off
    rationale   TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);

-- Immutable consensus decision ledger: decisions include non-trades, so volume
-- loss can be attributed to vote quality, conflict policy, or risk capacity.
CREATE TABLE IF NOT EXISTS consensus_decisions (
    decision_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT,
    score REAL,
    opposing REAL,
    stance_count INTEGER,
    diagnostics TEXT NOT NULL,
    disposition TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consensus_decisions_experiment_ts
    ON consensus_decisions(experiment_id, ts);

-- Decision-to-outcome ledger. One row is created for every consensus verdict;
-- it is updated through guarded lifecycle transitions instead of being inferred
-- from timestamps or client-id naming conventions.
CREATE TABLE IF NOT EXISTS consensus_lifecycle (
    decision_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    analytical_action TEXT NOT NULL,
    analytical_reason TEXT NOT NULL,
    side TEXT,
    book TEXT NOT NULL,
    feed_provenance TEXT NOT NULL,
    config_snapshot_hash TEXT NOT NULL,
    strategy_registry_hash TEXT NOT NULL,
    code_version TEXT NOT NULL,
    diagnostics TEXT NOT NULL,
    terminal_state TEXT NOT NULL,
    client_id TEXT,
    trade_id TEXT,
    realised_pnl REAL,
    risk_rule TEXT,
    risk_detail TEXT,
    compliance_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consensus_lifecycle_ts ON consensus_lifecycle(ts);
CREATE INDEX IF NOT EXISTS idx_consensus_lifecycle_terminal ON consensus_lifecycle(terminal_state);

CREATE TABLE IF NOT EXISTS learning_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    hypothesis    TEXT,
    param_updates TEXT,
    accepted      INTEGER NOT NULL,     -- 0/1
    sharpe_before REAL,
    sharpe_after  REAL
);
CREATE INDEX IF NOT EXISTS idx_learning_strategy ON learning_events(strategy);

-- Closed-bar price history, accumulated as the agent runs. This is the
-- validation backbone: walk-forward gates replay proposals against it
-- instead of re-scoring the same journal rows they were fitted on.
CREATE TABLE IF NOT EXISTS candles (
    symbol    TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts        TEXT NOT NULL,
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    volume    REAL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe, ts)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # timeout: don't fail instantly if another connection (dashboard,
        # reflection worker) briefly holds the write lock. WAL lets readers
        # and one writer coexist without blocking each other.
        self.conn = sqlite3.connect(str(path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            # WAL + NORMAL is the standard durability/latency trade: fsync on
            # checkpoint, not on every commit. The journal is rebuilt from the
            # broker on restart, so losing the last few ms of writes on power
            # cut is acceptable; blocking the trading loop on fsync is not.
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass   # e.g. read-only or network filesystem; default mode still works
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(trades)")}
        if "mode" not in cols:
            self.conn.execute("ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'real'")
        # Signals gained recommended sizing/brackets + a linkable id + graded
        # outcome so the dashboard can show lot/TP/SL and WIN/LOSS per signal.
        scols = {r["name"] for r in self.conn.execute("PRAGMA table_info(signals)")}
        for col, ddl in (("lot", "REAL"), ("take_profit", "REAL"),
                         ("stop_loss", "REAL"), ("pnl", "REAL"), ("client_id", "TEXT"),
                         # Soft context at decision time, for the Signals tab:
                         # LLM sentiment score and the RL policy's P(take).
                         ("sentiment", "REAL"), ("rl_p", "REAL"),
                         ("rejection_reason", "TEXT"), ("rejection_detail", "TEXT"),
                         ("decision_id", "TEXT")):
            if col not in scols:
                self.conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {ddl}")

    # ── immutable execution lineage ─────────────────────────────────────────

    def record_order_intent(self, *, client_id: str, signal_id: str | None, ts: str,
                            symbol: str, side: str, intended_size: float, mode: str,
                            decision_price: float | None, cost_model: dict) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO order_intents (client_id,signal_id,ts,symbol,side,intended_size,mode,decision_price,cost_model,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (client_id, signal_id, ts, symbol, side, intended_size, mode, decision_price,
             json.dumps(cost_model, sort_keys=True), _now()),
        )
        self.conn.commit()

    def record_execution_event(self, *, client_id: str, event_type: str, ts: str,
                               broker_id: str | None, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO execution_events (client_id,event_type,ts,broker_id,payload,created_at) VALUES (?,?,?,?,?,?)",
            (client_id, event_type, ts, broker_id, json.dumps(payload, sort_keys=True), _now()),
        )
        self.conn.commit()

    def record_reconciliation_event(self, *, client_id: str, ts: str, source: str,
                                    status: str, detail: dict) -> None:
        self.conn.execute(
            "INSERT INTO reconciliation_events (client_id,ts,source,status,detail,created_at) VALUES (?,?,?,?,?,?)",
            (client_id, ts, source, status, json.dumps(detail, sort_keys=True), _now()),
        )
        self.conn.commit()

    # ── candles (validation history) ─────────────────────────────────────────

    def store_candles(self, candles: list) -> int:
        """Insert closed bars, ignoring ones already stored. Returns rows added."""
        if not candles:
            return 0
        rows = [(c.symbol, c.timeframe, c.ts.isoformat(), c.open, c.high, c.low,
                 c.close, c.volume) for c in candles]
        cur = self.conn.executemany(
            """INSERT OR IGNORE INTO candles
               (symbol, timeframe, ts, open, high, low, close, volume)
               VALUES (?,?,?,?,?,?,?,?)""", rows)
        self.conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def load_candles(self, symbol: str, timeframe: str, limit: int = 2000) -> list:
        """Chronological (oldest-first) stored bars for a symbol/timeframe."""
        from ..data.models import Candle
        rows = self.conn.execute(
            """SELECT * FROM (SELECT * FROM candles WHERE symbol=? AND timeframe=?
               ORDER BY ts DESC LIMIT ?) ORDER BY ts ASC""",
            (symbol, timeframe, limit)).fetchall()
        return [Candle(symbol=r["symbol"], timeframe=r["timeframe"],
                       open=r["open"], high=r["high"], low=r["low"],
                       close=r["close"], volume=r["volume"] or 0.0,
                       ts=datetime.fromisoformat(r["ts"])) for r in rows]

    def candle_count(self, symbol: str, timeframe: str) -> int:
        r = self.conn.execute(
            "SELECT COUNT(*) AS n FROM candles WHERE symbol=? AND timeframe=?",
            (symbol, timeframe)).fetchone()
        return int(r["n"]) if r else 0

    # ── trades ───────────────────────────────────────────────────────────────

    def record_trade(self, trade: Trade) -> int:
        cur = self.conn.execute(
            """INSERT INTO trades
               (symbol, side, volume, entry_price, exit_price, pnl, strategy,
                mode, opened_at, closed_at, context)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade.symbol,
                trade.side.value,
                trade.volume,
                trade.entry_price,
                trade.exit_price,
                trade.pnl,
                trade.strategy,
                trade.mode,
                trade.opened_at.isoformat(),
                trade.closed_at.isoformat() if trade.closed_at else None,
                json.dumps(trade.context),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_trades(
        self, strategy: str | None = None, mode: str | None = None, limit: int = 100,
        closed_only: bool = False,
    ) -> list[Trade]:
        where, args = [], []
        if strategy:
            where.append("strategy=?")
            args.append(strategy)
        if mode:
            where.append("mode=?")
            args.append(mode)
        if closed_only:
            # Filter in SQL, not post-limit in Python — otherwise a window of
            # "the last N trades" silently shrinks to however many were closed.
            where.append("closed_at IS NOT NULL")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        args.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM trades{clause} ORDER BY id DESC LIMIT ?", args
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def prune_signals(self, retention_days: int = 90) -> int:
        """Delete rejected-signal rows older than the retention window.

        The signals table is the only unbounded one (26 strategies × every bar).
        Executed/graded signals (real/shadow, or carrying a pnl) are kept — they
        are the learning record; stale *rejections* are just veto telemetry."""
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=retention_days)).isoformat()
        cur = self.conn.execute(
            "DELETE FROM signals WHERE ts < ? AND disposition LIKE 'rejected%' "
            "AND pnl IS NULL", (cutoff,))
        self.conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def trade_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT mode, COUNT(*) n FROM trades GROUP BY mode"
        ).fetchall()
        return {r["mode"] or "real": r["n"] for r in rows}

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _row_to_trade(r: sqlite3.Row) -> Trade:
        keys = r.keys()
        # Load the persisted timestamps instead of letting them default to now() —
        # the equity curve, ordering and drawdown all depend on real trade times.
        opened = Database._parse_dt(r["opened_at"]) if "opened_at" in keys else None
        closed = Database._parse_dt(r["closed_at"]) if "closed_at" in keys else None
        fields = dict(
            symbol=r["symbol"],
            side=Side(r["side"]),
            volume=r["volume"],
            entry_price=r["entry_price"],
            exit_price=r["exit_price"],
            pnl=r["pnl"],
            strategy=r["strategy"] or "",
            mode=(r["mode"] if "mode" in keys else "real") or "real",
            context=json.loads(r["context"]) if r["context"] else {},
        )
        if opened is not None:
            fields["opened_at"] = opened
        if closed is not None:
            fields["closed_at"] = closed
        return Trade(**fields)

    # ── consensus decisions ──────────────────────────────────────────────────

    def record_consensus_verdict(self, *, decision_id: str, experiment_id: str,
                                 ts: str, symbol: str, action: str,
                                 side: str | None, score: float, opposing: float,
                                 stance_count: int, diagnostics: dict,
                                 disposition: str, analytical_reason: str,
                                 book: str, feed_provenance: str,
                                 config_snapshot_hash: str,
                                 strategy_registry_hash: str, code_version: str) -> None:
        """Persist one immutable verdict and its pending lifecycle atomically."""
        now = _now()
        with self.conn:
            self.conn.execute(
                """INSERT INTO consensus_decisions
                   (decision_id,experiment_id,ts,symbol,action,side,score,opposing,
                    stance_count,diagnostics,disposition,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (decision_id, experiment_id, ts, symbol, action, side, score, opposing,
                 stance_count, json.dumps(diagnostics, sort_keys=True), disposition, now),
            )
            self.conn.execute(
                """INSERT INTO consensus_lifecycle
                   (decision_id,experiment_id,ts,symbol,analytical_action,analytical_reason,
                    side,book,feed_provenance,config_snapshot_hash,strategy_registry_hash,
                    code_version,diagnostics,terminal_state,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (decision_id, experiment_id, ts, symbol, action, analytical_reason, side,
                 book, feed_provenance, config_snapshot_hash, strategy_registry_hash,
                 code_version, json.dumps(diagnostics, sort_keys=True), "pending", now, now),
            )

    def record_consensus_decision(self, *, decision_id: str, experiment_id: str,
                                  ts: str, symbol: str, action: str,
                                  side: str | None, score: float, opposing: float,
                                  stance_count: int, diagnostics: dict,
                                  disposition: str) -> None:
        self.conn.execute(
            """INSERT INTO consensus_decisions
               (decision_id,experiment_id,ts,symbol,action,side,score,opposing,
                stance_count,diagnostics,disposition,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, experiment_id, ts, symbol, action, side, score, opposing,
             stance_count, json.dumps(diagnostics, sort_keys=True), disposition, _now()),
        )
        self.conn.commit()

    # ── consensus lifecycle ─────────────────────────────────────────────────

    def record_consensus_lifecycle(self, *, decision_id: str, experiment_id: str,
                                   ts: str, symbol: str, analytical_action: str,
                                   analytical_reason: str, side: str | None,
                                   book: str, feed_provenance: str,
                                   config_snapshot_hash: str,
                                   strategy_registry_hash: str, code_version: str,
                                   diagnostics: dict) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO consensus_lifecycle
               (decision_id,experiment_id,ts,symbol,analytical_action,analytical_reason,
                side,book,feed_provenance,config_snapshot_hash,strategy_registry_hash,
                code_version,diagnostics,terminal_state,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, experiment_id, ts, symbol, analytical_action,
             analytical_reason, side, book, feed_provenance, config_snapshot_hash,
             strategy_registry_hash, code_version, json.dumps(diagnostics, sort_keys=True),
             "pending", now, now),
        )
        self.conn.commit()

    def update_consensus_lifecycle(self, decision_id: str, *, terminal_state: str,
                                   client_id: str | None = None,
                                   trade_id: str | None = None,
                                   realised_pnl: float | None = None,
                                   risk_rule: str | None = None,
                                   risk_detail: dict | None = None,
                                   compliance_reason: str | None = None) -> None:
        row = self.conn.execute(
            "SELECT terminal_state FROM consensus_lifecycle WHERE decision_id=?", (decision_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown consensus decision: {decision_id}")
        prior = str(row["terminal_state"])
        transitions = {
            "pending": {"not_submitted", "opened_real", "opened_shadow", "rejected_risk",
                        "rejected_compliance", "rejected_consensus", "failed_execution"},
            "opened_real": {"closed", "failed_execution"},
            "opened_shadow": {"closed", "failed_execution"},
        }
        if terminal_state not in transitions.get(prior, set()):
            raise ValueError(f"invalid consensus lifecycle transition from terminal state: {prior} -> {terminal_state}")
        self.conn.execute(
            """UPDATE consensus_lifecycle SET terminal_state=?,
               client_id=COALESCE(?, client_id), trade_id=COALESCE(?, trade_id),
               realised_pnl=COALESCE(?, realised_pnl), risk_rule=COALESCE(?, risk_rule),
               risk_detail=COALESCE(?, risk_detail), compliance_reason=COALESCE(?, compliance_reason), updated_at=?
               WHERE decision_id=?""",
            (terminal_state, client_id, trade_id, realised_pnl, risk_rule,
             json.dumps(risk_detail, sort_keys=True) if risk_detail is not None else None,
             compliance_reason, _now(), decision_id),
        )
        self.conn.commit()

    def recent_consensus_evidence(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """SELECT cl.*, cd.decision_id AS decision_decision_id, cd.action AS decision_action,
                      cd.disposition AS decision_disposition, cd.score AS decision_score,
                      cd.opposing AS decision_opposing, cd.stance_count AS decision_stance_count,
                      cd.diagnostics AS decision_diagnostics, s.id AS signal_id,
                      s.client_id AS signal_client_id, s.disposition AS signal_disposition,
                      s.pnl AS signal_pnl, s.rejection_reason AS signal_rejection_reason,
                      t.id AS trade_row_id, t.symbol AS trade_symbol, t.side AS trade_side,
                      t.mode AS trade_mode, t.pnl AS trade_pnl, t.entry_price AS trade_entry_price,
                      t.exit_price AS trade_exit_price, t.opened_at AS trade_opened_at,
                      t.closed_at AS trade_closed_at
               FROM consensus_lifecycle cl
               LEFT JOIN consensus_decisions cd ON cd.decision_id=cl.decision_id
               LEFT JOIN signals s ON s.id=(SELECT s2.id FROM signals s2
                   WHERE s2.decision_id=cl.decision_id ORDER BY s2.id DESC LIMIT 1)
               LEFT JOIN trades t ON CAST(t.id AS TEXT)=cl.trade_id
               ORDER BY cl.ts DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["diagnostics"] = json.loads(item["diagnostics"])
            item["risk_detail"] = json.loads(item["risk_detail"]) if item["risk_detail"] else None
            decision_diagnostics = item.pop("decision_diagnostics")
            item["decision"] = {"decision_id": item.pop("decision_decision_id"),
                "action": item.pop("decision_action"), "disposition": item.pop("decision_disposition"),
                "score": item.pop("decision_score"), "opposing": item.pop("decision_opposing"),
                "stance_count": item.pop("decision_stance_count"),
                "diagnostics": json.loads(decision_diagnostics) if decision_diagnostics else None}
            item["signal"] = {"id": item.pop("signal_id"), "client_id": item.pop("signal_client_id"),
                "disposition": item.pop("signal_disposition"), "pnl": item.pop("signal_pnl"),
                "rejection_reason": item.pop("signal_rejection_reason")}
            item["trade"] = {"id": item.pop("trade_row_id"), "symbol": item.pop("trade_symbol"),
                "side": item.pop("trade_side"), "mode": item.pop("trade_mode"),
                "pnl": item.pop("trade_pnl"), "entry_price": item.pop("trade_entry_price"),
                "exit_price": item.pop("trade_exit_price"), "opened_at": item.pop("trade_opened_at"),
                "closed_at": item.pop("trade_closed_at")}
            out.append(item)
        return out

    # ── signals ──────────────────────────────────────────────────────────────

    def record_signal(self, signal: Signal, disposition: str, price: float | None,
                      lot: float | None = None, take_profit: float | None = None,
                      stop_loss: float | None = None, client_id: str | None = None,
                      sentiment: float | None = None, rl_p: float | None = None,
                      rejection_reason: str | None = None,
                      rejection_detail: dict | None = None,
                      decision_id: str | None = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO signals
               (ts, strategy, symbol, side, conviction, price, disposition, rationale,
                lot, take_profit, stop_loss, client_id, sentiment, rl_p,
                rejection_reason, rejection_detail, decision_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal.ts.isoformat(), signal.strategy, signal.symbol, signal.side.value,
                signal.conviction, price, disposition, signal.rationale,
                lot, take_profit, stop_loss, client_id, sentiment, rl_p,
                rejection_reason, json.dumps(rejection_detail) if rejection_detail else None,
                decision_id,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_signal_outcome(self, client_id: str, pnl: float) -> None:
        """Grade the (executed) signal that produced a now-closed trade."""
        self.conn.execute(
            "UPDATE signals SET pnl=? WHERE client_id=? AND pnl IS NULL",
            (pnl, client_id),
        )
        self.conn.commit()

    def recent_signals(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["rejection_detail"] = (json.loads(item["rejection_detail"])
                                        if item.get("rejection_detail") else None)
            out.append(item)
        return out

    # ── learning ─────────────────────────────────────────────────────────────

    def record_learning_event(
        self,
        strategy: str,
        hypothesis: str,
        param_updates: dict,
        accepted: bool,
        sharpe_before: float | None = None,
        sharpe_after: float | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO learning_events
               (ts, strategy, hypothesis, param_updates, accepted, sharpe_before, sharpe_after)
               VALUES (?,?,?,?,?,?,?)""",
            (_now(), strategy, hypothesis, json.dumps(param_updates),
             1 if accepted else 0, sharpe_before, sharpe_after),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_learning_events(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM learning_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["param_updates"] = json.loads(d["param_updates"]) if d["param_updates"] else {}
            d["accepted"] = bool(d["accepted"])
            out.append(d)
        return out

    def reset_all(self) -> dict[str, int]:
        """Wipe trade history: trades, signals, and learning events.

        Deliberately KEEPS the `candles` table — those are cached market price
        bars (the walk-forward validation backbone), not trade history, and
        re-accumulating them is slow and costs API calls. Returns the row count
        deleted per table so the caller can log/confirm what was cleared.
        """
        counts: dict[str, int] = {}
        for table in ("trades", "signals", "learning_events"):
            cur = self.conn.execute(f"DELETE FROM {table}")
            counts[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        self.conn.commit()
        # Reclaim the freed pages so the file actually shrinks on disk.
        try:
            self.conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass  # VACUUM can't run inside a transaction on some builds; harmless
        return counts

    def close(self) -> None:
        self.conn.close()
