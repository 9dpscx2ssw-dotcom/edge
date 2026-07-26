# Odin dashboard — React source

This is the source for `../static/index.html`. It builds to a single,
self-contained HTML file — React and ReactDOM are bundled inline via esbuild,
no CDN and no separate `.js`/`.css` assets — because `server.py` serves
`static/index.html` directly (`FileResponse`) with no build step in
production.

## Rebuild after any change here

```bash
cd src/gungnir/dashboard/react-src
npm install        # first time only
npm run build       # writes ../static/index.html
```

`static/index.html` is a **generated file** — commit it alongside source
changes here, but always edit the `.jsx`/`.js`/`.css` files, never the
generated HTML directly.

## Layout

- `App.jsx` — shell: sidebar nav, topbar (equity/P&L, kill switch, agent
  toggle, RL veto, mode), tab routing.
- `tabs/*.jsx` — one file per nav tab (Overview, Markets, Strategies,
  Learning, Signals, Trades, Reports, Backtest, Settings).
- `components.jsx` — shared Card/Badge/SortTable/`usePoll` (the polling hook
  each tab uses to call its `GET` endpoint).
- `charts.jsx` — dependency-free Canvas 2D charts (sparkline, equity curve,
  bar chart, take-rate/epsilon chart). No Chart.js/CDN.
- `api.js` — fetch wrapper matching the original dashboard's token/401/retry
  contract (`X-Dashboard-Token`, prompts once on 401, retries).
- `format.js` — `usd`/`signed`/`pct`/`timeAgo` formatting helpers.

## Scope notes

- **Polling cadence matches the original exactly**: Settings, Backtest, and
  Reports load once per tab switch (`NO_POLL` in `App.jsx`) so a 5s refresh
  never clobbers an in-progress form edit or re-runs a heavy aggregation;
  every other tab polls its endpoint every 5s while active.
- **Reports tab is intentionally simplified.** The original is a bespoke
  analytics surface (donut charts, diverging instrument bars, a custom
  heatmap-per-cell scorecard). This port keeps the same real
  `/api/performance` data — KPI tiles with sparklines, the equity curve,
  per-strategy/per-instrument tables — without cloning every custom SVG
  widget. Functionally equivalent data, less bespoke chrome.
- **New (additive, read-only) backend endpoint**: `GET /api/backtest` used to
  be a stub returning `{}`. It now serves the last cached
  `scripts/backtest_all_strategies.py` run (`data/backtest_all_strategies.json`)
  if present, still `{}` otherwise — this powers the Strategies-tab backtest
  PF heatmap. See `test_get_backtest_serves_cached_all_strategies_run` in
  `tests/test_backtest_cached_candles.py`.
