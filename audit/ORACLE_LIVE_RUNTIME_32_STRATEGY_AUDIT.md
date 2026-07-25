# Oracle live-runtime deep volume audit — 32 strategies + consensus

## Limitations

- Snapshot: running `oracle:/app/data` captured at `20260724T1113Z`; SQLite backup SHA-256 `845882a881c06239ccf3be3c0fe8512e9fbad65ba48b9c6753adf2344294d008`; integrity `ok`; 485 closed trades from `2026-07-23T12:14:46Z` to `2026-07-24T09:16:35Z`.
- Internal runtime P&L only. No broker reconciliation, independent market-data replay, fee/financing proof, or fill-quality validation is available; results cannot support live promotion.
- Base strategy rows are attribution/shadow streams under a consensus/netting architecture, not independent executable portfolios; do not sum them with consensus.
- Most recommended fixes are not historically replayable because rejected outcomes, exact decision-time feature values, alternate exits/fills/costs, and skip outcomes were not persisted.
- All `n<30` cells are **DESCRIPTIVE ONLY**; `30–99` cells are **PROVISIONAL**. No strategy passes institutional promotion gates.

## Runtime evidence sources

- Authoritative runtime directory: captured `oracle:/app/data` from Docker volume `oracle_oracle-data`.
- Included runtime data: `control.json`, `status.json`, `strategies.yaml`, `risk_state.json`, `rl_policy*.npz`, `rl_convergence.jsonl`, `audit.jsonl`, `gungnir.db`, `gungnir.db-wal`, `gungnir.db-shm`, and runtime `backups/`.
- `/app/data/config.json` was absent at capture time; mounted config present was `/app/config/config.yaml`.

## System-wide current result

| Ledger | n | Net | Mean | Win rate | 95% Wilson | PF | Status |
|---|---:|---:|---:|---:|---|---:|---|
| Base attribution | 342 | `-286.599` | `-0.838` | 29.8% | [25.2%, 34.9%] | 0.688 | PROVISIONAL—execution evidence missing |
| Consensus meta-book | 143 | `-741.425` | `-5.185` | 16.1% | [11.0%, 23.0%] | 0.156 | PROVISIONAL—execution evidence missing |

## Every available strategy — current runtime diagnostics

| # | Strategy | n | Net | Mean | Win rate | PF | Top regime | Family-screen retained | Counterfactual status | Main intervention |
|---:|---|---:|---:|---:|---:|---:|---|---|---|---|
| 1 | `adx_momentum_ema` | 14 | `-30.035` | `-2.145` | 28.6% | 0.538 | trend_high (5) | 9/14 net `-2.015` | recommended economic fixes not identifiable | P1: require rising ADX/fresh DI-momentum alignment, EMA slope and volume; reconcile timeframe. |
| 2 | `alligator` | 6 | `3.672` | `0.612` | 50.0% | 1.224 | trend_low (2) | 4/6 net `17.452` | engineering/source/logging only; family screen exploratory | P1: require line-spread expansion and fresh ordering transition with SMA slope/ADX confirmation. |
| 3 | `ao_macd` | 6 | `51.803` | `8.634` | 33.3% | 11.588 | trend_high (3) | 6/6 net `51.803` | engineering/source/logging only; family screen exploratory | P0: map to trend; require recent synchronized zero cross and slope/ATR extension limit. |
| 4 | `bb_macd_sma` | 9 | `-16.210` | `-1.801` | 33.3% | 0.550 | range_high (6) | 9/9 net `-16.210` | recommended economic fixes not identifiable | P0: remap to trend or change thesis to fade; implement/remove SMA2; require fresh cross and expansio |
| 5 | `bb_rsi` | 3 | `4.288` | `1.429` | 66.7% | 2.731 | trend_low (2) | 2/3 net `0.090` | engineering/source/logging only; family screen exploratory | P0: resolve thesis: reverse sides plus re-entry for mean reversion, or remap to trend and add expans |
| 6 | `bb_rsi_cutting` | 1 | `1.092` | `1.092` | 100.0% | — | trend_low (1) | 1/1 net `1.092` | engineering/source/logging only; family screen exploratory | P1: retain ADX ceiling, add cross-back/rejection and width/volume; reconcile periods/timeframe. |
| 7 | `cci200_ema_pivot` | 21 | `-53.298` | `-2.538` | 28.6% | 0.410 | trend_high (11) | 16/21 net `-28.988` | recommended economic fixes not identifiable | P0: define correct pivot horizon, map to trend, require fresh alignment/slope and volume. |
| 8 | `cci_macd` | 13 | `49.429` | `3.802` | 53.8% | 4.363 | trend_high (8) | 9/13 net `40.436` | engineering/source/logging only; family screen exploratory | P0: map to trend, reconcile timeframe, require fresh threshold event/MACD acceleration and anti-exte |
| 9 | `cci_reversal` | 4 | `-29.041` | `-7.260` | 0.0% | 0.000 | trend_high (2) | 2/4 net `-2.055` | engineering/source/logging only; family screen exploratory | P1: require CCI cross-back/rejection and cap trend strength; map stop to swing/structure. |
| 10 | `ema78_crossover_m15` | 16 | `-41.316` | `-2.582` | 25.0% | 0.302 | range_high (7) | 9/16 net `-30.080` | strict EMA range screen available; still negative | P0: map to trend; add normalized separation and follow-through confirmation. |
| 11 | `ema78_crossover_m5` | 30 | `-82.910` | `-2.764` | 26.7% | 0.120 | trend_low (13) | 17/30 net `-36.176` | strict EMA range screen available; still negative | P0: map both variants to trend; require post-cross separation >= ATR fraction and slope/ADX/HTF conf |
| 12 | `ema921_adx_dmi_m15` | 0 | `0.000` | `—` | — | — | — | 0/0 net `0.000` | engineering/source/logging only; family screen exploratory | P0: map to trend and instrument each failed conjunct; require separation/volume only if adequate sig |
| 13 | `ema921_adx_dmi_m5` | 5 | `-16.946` | `-3.389` | 0.0% | 0.000 | trend_high (2) | 3/5 net `-14.510` | engineering/source/logging only; family screen exploratory | P0: map to trend; require rising ADX and minimum post-cross separation/volume, while monitoring over |
| 14 | `ema_stoch_rsi` | 8 | `-15.201` | `-1.900` | 12.5% | 0.138 | trend_high (3) | 8/8 net `-15.201` | recommended economic fixes not identifiable | P0: map oscillator family; require fresh EMA/RSI event and meaningful stochastic turn/%D confirmatio |
| 15 | `fvg_m1` | 30 | `-34.702` | `-1.157` | 30.0% | 0.115 | range_low (11) | 25/30 net `-30.672` | recommended economic fixes not identifiable | P0: first-retest-only, gap size >= spread/ATR budget, displacement volume and rejection; expire rapi |
| 16 | `fvg_m15` | 8 | `-16.398` | `-2.050` | 0.0% | 0.000 | range_high (5) | 8/8 net `-16.398` | recommended economic fixes not identifiable | P0: first retest and rejection with age/size/volume/trend gates. |
| 17 | `fvg_m30` | 4 | `-16.365` | `-4.091` | 0.0% | 0.000 | range_high (2) | 3/4 net `-10.887` | recommended economic fixes not identifiable | P0: enter only first retest of a fresh unmitigated gap with rejection close and trend/volume confirm |
| 18 | `fvg_m5` | 21 | `-9.183` | `-0.437` | 38.1% | 0.726 | range_high (9) | 19/21 net `-7.592` | recommended economic fixes not identifiable | P0: first retest of unmitigated gap, rejection close, displacement/volume and regime confirmation. |
| 19 | `hma_dc_d1` | 5 | `-18.521` | `-3.704` | 20.0% | 0.462 | trend_high (3) | 3/5 net `-16.531` | engineering/source/logging only; family screen exploratory | P1: true channel breakout/retest plus HMA slope; explicit data sufficiency and stale-bar checks. |
| 20 | `hma_dc_h1` | 7 | `67.330` | `9.619` | 57.1% | 15.570 | trend_high (3) | 6/7 net `69.278` | engineering/source/logging only; family screen exploratory | P1: require HMA slope and either true channel breakout or explicit pullback setup; gate narrow chann |
| 21 | `hma_dc_h4` | 6 | `78.125` | `13.021` | 50.0% | 14.677 | trend_high (4) | 4/6 net `79.962` | engineering/source/logging only; family screen exploratory | P1: require HMA slope and true channel break/retest; avoid duplicated lower-horizon agreement inflat |
| 22 | `hma_dc_m1` | 30 | `-50.439` | `-1.681` | 10.0% | 0.037 | trend_high (12) | 26/30 net `-48.906` | recommended economic fixes not identifiable | P0: require true channel break/retest, minimum width/volume, hard spread-to-ATR budget; otherwise di |
| 23 | `hma_dc_m15` | 20 | `-15.250` | `-0.762` | 35.0% | 0.739 | trend_high (7) | 15/20 net `3.296` | recommended economic fixes not identifiable | P1: define break or pullback, require slope/width and coordinate duplicate horizons. |
| 24 | `hma_dc_m5` | 25 | `-55.084` | `-2.203` | 32.0% | 0.266 | trend_high (13) | 21/25 net `-48.675` | recommended economic fixes not identifiable | P0: true breakout or pullback definition, HMA slope, channel width and spread/ATR guard. |
| 25 | `intelligent_trading` | 0 | `0.000` | `—` | — | — | — | 0/0 net `0.000` | engineering/source/logging only; family screen exploratory | P0: map to trend, validate stochastic inequality intent, instrument conjunct attrition; require fres |
| 26 | `macd_stoch` | 3 | `-2.072` | `-0.691` | 33.3% | 0.550 | trend_low (2) | 3/3 net `-2.072` | engineering/source/logging only; family screen exploratory | P0: map oscillator family; reconcile documented periods/timeframe; require K/%D turn and MACD accele |
| 27 | `mean_reversion` | 3 | `-21.296` | `-7.099` | 33.3% | 0.058 | trend_low (2) | 2/3 net `-6.475` | recommended economic fixes not identifiable | P1: require close back inside band/reversal and range eligibility; specify sentiment-missing behavio |
| 28 | `multi_bb` | 5 | `-24.316` | `-4.863` | 20.0% | 0.053 | trend_low (3) | 3/5 net `-7.401` | engineering/source/logging only; family screen exploratory | P0: implement true multi-deviation design or rename; require re-entry/reversal and range/width eligi |
| 29 | `parsar_cci_ema` | 7 | `36.938` | `5.277` | 71.4% | 47.715 | trend_high (5) | 6/7 net `37.666` | engineering/source/logging only; family screen exploratory | P1: require fresh SAR/CCI event, EMA slope/volume and non-extended price; reconcile intended timefra |
| 30 | `scalp_ema_vwap_m1` | 16 | `-25.765` | `-1.610` | 18.8% | 0.071 | range_high (8) | 15/16 net `-24.502` | recommended economic fixes not identifiable | P0: resolve EMA5/9, set validated nonzero gap threshold, require fresh cross, VWAP slope/volume and  |
| 31 | `scalp_ema_vwap_m5` | 8 | `-9.754` | `-1.219` | 50.0% | 0.622 | range_high (3) | 6/8 net `-12.694` | recommended economic fixes not identifiable | P0: resolve EMA period; validated nonzero gap, fresh cross, slope/volume and cost budget. |
| 32 | `trend_following` | 8 | `4.826` | `0.603` | 37.5% | 1.167 | trend_high (4) | 6/8 net `13.252` | engineering/source/logging only; family screen exploratory | P0: make equality neutral; require fresh cross or sustained normalized separation/slope; explicitly  |

## Exact counterfactual results for recommended fixes

### Base strategies

| Strategy | Fix | Raw | Retained | Excluded | Interpretation |
|---|---|---:|---:|---:|---|
| `ema78_crossover_m5` | trend-family mapping + avoid `range_*` | 30 / `-82.910` / 26.7% | 17 / `-36.176` / 23.5% | 13 / `-46.734` / 30.8% | improves mean but still negative |
| `ema78_crossover_m15` | trend-family mapping + avoid `range_*` | 16 / `-41.316` / 25.0% | 9 / `-30.080` / 22.2% | 7 / `-11.236` / 28.6% | worse/unchanged and still negative |

- For the other 30 strategies, the recommended quality fixes require missing decision-time/rejected-signal/alternate-exit data. They are not honest numerical counterfactuals on this ledger.
- The complete family/regime screen is supplied for every strategy as an exploratory observed-row filter in `strategy_family_regime_screen.csv`; it is not a causal replay.

### Exploratory system-wide family/regime screen

| Population | Raw | Retained | Excluded |
|---|---:|---:|---:|
| Base attribution rows | 342 / `-286.599` / 29.8% | 266 / `-63.713` / 32.0% | 76 / `-222.885` / 22.4% |

## System-wide confidence and correctness

| Ledger | Coverage | Mean recorded confidence | Observed win rate | Raw gap | Interpretation |
|---|---:|---:|---:|---:|---|
| base_attribution | 341/342 | 62.2% | 29.9% [25.3%, 35.0%] | 32.3% | diagnostic only; not calibrated P(win) |
| consensus | 142/143 | 86.4% | 16.2% [11.0%, 23.1%] | 70.2% | diagnostic only; not calibrated P(win) |

## Counterfactual consensus performance

| Cohort | n | Net | Mean | Win rate | PF | Status |
|---|---:|---:|---:|---:|---:|---|
| raw_strict_join | 142 | `-741.418` | `-5.221` | 16.2% | 0.156 | PROVISIONAL—execution evidence missing |
| zero_effective_excluded | 67 | `-664.447` | `-9.917` | 0.0% | 0.000 | PROVISIONAL |
| retained_after_zero_vote_guard | 75 | `-76.971` | `-1.026` | 30.7% | 0.640 | PROVISIONAL |

Interpretation: the zero-effective-vote guard is the only exact consensus repair with a strict decision→lifecycle→trade join. It removes known zero-vote observed entries; retained performance must still be judged by its net/mean/win rate above and remains subject to sample/lineage limits.

## Why strategies are winning/failing

1. Apparent winners are mostly small-sample or outlier-driven; no arm has broker-reconciled stable evidence.
2. Losing clusters concentrate in level-state entries without fresh event confirmation, especially EMA/HMA/FVG/scalp short horizons.
3. Entry quality defects dominate: missing normalized separation, slope, first-retest, width, volume/liquidity, spread-to-edge, and session filters.
4. Exit quality is generic across all families, so mean-reversion, trend, structure and scalp hypotheses are exited with the same 2ATR/3ATR + breakeven mechanics.
5. Confidence is semantically overstated versus observed correctness and should not size or promote strategies until calibrated.
6. RL and filter value cannot be causally measured without persisted TAKE/SKIP outcomes and complete feature snapshots.

## Recommended intervention order

- **P0 correctness/lineage:** authoritative strategy family for all 32 names, preserve exact runtime config/code hashes, persist feature snapshots and close reasons, and keep `/app/data` packaged for every audit.
- **P1 entry-quality shadow arms:** fresh-cross/first-retest rules, normalized gap/slope/ADX/volume/spread-to-edge gates, FVG age/fill-state/rejection fields, HMA true breakout/retest definitions.
- **P1 exit-quality shadow arms:** thesis-specific exits: mean target for reversion, trailing/slope invalidation for trend, structure invalidation for FVG/channel, VWAP recross/time stop for scalp.
- **P1 consensus:** shadow-test zero-effective-vote rejection and report separate retained/excluded outcome; do not promote until retained cohort turns positive on a pre-registered holdout.
- **P2 release gates:** chronological holdouts, multiplicity controls, broker fill reconciliation, external cost stress, and calibrated confidence before any live activation.

## Artifact index

- `reports/ORACLE_LIVE_RUNTIME_32_STRATEGY_AUDIT.md`
- `tables/per_strategy_metrics.csv`
- `tables/subgroup_metrics.csv`
- `tables/exact_base_screens.csv`
- `tables/strategy_family_regime_screen.csv`
- `tables/confidence_correctness.csv`
- `tables/consensus_zero_vote_counterfactual.csv`
- `tables/consensus_strict_join_ledger.csv`
- `tables/strategy_fix_inventory_current.csv`
- `snapshots/current-runtime-gungnir.sqlite` and `snapshots/MANIFEST.json`
