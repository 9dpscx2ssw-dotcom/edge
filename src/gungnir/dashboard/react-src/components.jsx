import React, { useEffect, useRef, useState, useCallback } from "react";
import { cx, pfClass } from "./format.js";
import { api } from "./api.js";

export function Card({ title, dim, right, foot, children, className, id }) {
  return (
    <div className={cx("card", className)} id={id}>
      {(title || right) && (
        <div className="card-head">
          {title && <h2>{title}{dim && <span className="dim"> {dim}</span>}</h2>}
          {right}
        </div>
      )}
      <div className="card-body">{children}</div>
      {foot && <div className="card-foot">{foot}</div>}
    </div>
  );
}
export const Badge = ({ kind = "off", children, title }) => <span className={cx("badge", kind)} title={title}>{children}</span>;
export const PFPill = ({ pf }) => <span className={cx("pf-pill", pfClass(pf))}>{pf == null ? "—" : (+pf).toFixed(2)}</span>;
export const Empty = ({ children }) => <div className="empty-state">{children}</div>;
export const Spinner = () => <div className="mini-spinner" aria-label="Loading" />;

/** Poll a GET endpoint on an interval; pause when the tab/card isn't visible on screen isn't tracked (kept simple: pauses when `enabled` is false, e.g. a background tab). */
export function usePoll(path, { intervalMs = 5000, enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const timer = useRef(null);
  const load = useCallback(async () => {
    try {
      const data = await api(path);
      setState({ data, error: null, loading: false });
    } catch (e) {
      setState((s) => ({ data: s.data, error: e.message, loading: false }));
    }
  }, [path]);
  useEffect(() => {
    if (!enabled) return;
    load();
    timer.current = setInterval(load, intervalMs);
    return () => clearInterval(timer.current);
  }, [load, intervalMs, enabled]);
  return { ...state, reload: load };
}

/** Sortable data table: pass columns [{key, label, left, render(row), sortValue(row)}] and rows. */
export function SortTable({ columns, rows, initialSort, rowKey, className }) {
  const [sort, setSort] = useState(initialSort || { key: columns[0].key, dir: -1 });
  const sortBy = (key) => setSort((s) => ({ key, dir: s.key === key ? -s.dir : -1 }));
  const col = columns.find((c) => c.key === sort.key);
  const sorted = rows.slice().sort((a, b) => {
    const av0 = col.sortValue ? col.sortValue(a) : a[sort.key];
    const bv0 = col.sortValue ? col.sortValue(b) : b[sort.key];
    if (typeof av0 === "string") return sort.dir * String(av0).localeCompare(String(bv0)) * -1;
    const av = av0 == null ? -Infinity : av0, bv = bv0 == null ? -Infinity : bv0;
    return sort.dir * (av - bv) * -1;
  });
  return (
    <table className={className}>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} className={cx(c.left && "left")} onClick={() => sortBy(c.key)} tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(c.key); } }}>
              {c.label} <span className="arrow">{sort.key === c.key ? (sort.dir === -1 ? "▾" : "▴") : ""}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.length === 0 && <tr><td className="left faint" colSpan={columns.length}>No rows.</td></tr>}
        {sorted.map((row) => (
          <tr key={rowKey(row)}>
            {columns.map((c) => <td key={c.key} className={cx(c.left && "left")}>{c.render ? c.render(row) : row[c.key]}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A toggle button matching the topbar's mode/agent/RL-veto/kill controls. */
export function ToggleBtn({ active, danger, onClick, title, children }) {
  return <button className={cx("toggle-btn", active && (danger ? "on-danger" : "on"))} title={title} onClick={onClick}>{children}</button>;
}
