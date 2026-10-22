# Architecture map

## Backend request path

```text
React UI
  -> FastAPI app/main.py
  -> Pydantic app/models.py
  -> DataStore app/data_store.py
  -> indicators.py + rules.py
  -> engine.py
  -> storage.py / results + .cache
```

### Core files

| File | Responsibility |
|---|---|
| `backend/app/main.py` | HTTP routes and job creation |
| `backend/app/models.py` | API/config schema, validation, backward migration |
| `backend/app/data_store.py` | archive/dataset resolution, CSV loading, higher-timeframe aggregation, quote SQLite indexes |
| `backend/app/indicators.py` | indicator catalog, registry, computations |
| `backend/app/rules.py` | condition operators and nested rule-group evaluation |
| `backend/app/engine.py` | strategy state, entries/exits, execution, P&L, fees, result creation |
| `backend/app/storage.py` | V15 result compression, usage, pinning, retention/cleanup |
| `backend/app/jobs.py` | background jobs, progress, cooperative cancellation |
| `backend/app/archive_sync.py` | plans/calls repository history archive sync |
| `backend/app/research.py` | parameter sweep, robustness, walk-forward, ablation |
| `backend/app/trend_discovery.py` | future-outcome research labels only |
| `backend/app/analysis.py` | post-run summaries/analysis package |

## Frontend

`App.tsx` coordinates datasets, strategy config, backtest jobs and current result. Specialized editors live under `src/components/`. Keep backend and `src/types.ts` contracts synchronized.

## Persistence

### Market data

Owned by repository `backtest/data/delta-history`, never copied into results.

### Quote indexes

`<app-folder>/.cache/quotes-*.sqlite3`. Expensive but derived/rebuildable. V15 reports them separately and does not delete them during result cleanup.

### Backtest results

V15/V15.1 storage profiles:

- `COMPACT`: compact `summary.json`, `strategy.json`, `trades.csv`.
- `ANALYSIS`: COMPACT + gzip-compressed markers, equity curve and retained decision events.
- `FULL_DEBUG`: COMPACT + uncompressed diagnostic artifacts for direct inspection.

`summary.json` must not embed duplicate full arrays.

### Cache identity

Backtest cache keys include engine version, source-file fingerprints, selection/range, strategy config and V15 storage mode. Increment the engine cache version when a behavior change can alter backtest results.

### V15.1 correctness-sensitive paths

- `data_store.py`: target candles use fixed UTC close buckets; selection start time must not alter overlapping OHLC.
- `indicators.py`: HTF aggregation uses datetime-aware Pandas resampling and is independent of ns/us internal units.
- `engine.py`: contract quantity validity is mandatory; strict budget is configurable; run directories are exclusive/unique.



### Daily historical levels (cache version 172)
`backend/app/day_levels.py` owns calendar snapshots and day-level parameter
validation. `indicators.py` exposes its outputs through the existing catalog;
`warmup.py` loads sufficient historical context and raw 5m range sources when
strategy bars are higher-timeframe. `alerts.py` can rearm by an optional numeric
identity operand. The shared example JSON is also the frontend toolbar preset.
Missing daily chart levels use whitespace points; saved result formats stay
compatible. See DAY_LEVEL_ALERTS.md.
