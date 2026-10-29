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

### Calendar and configurable session day boundaries (cache 173)
`backend/app/day_levels.py` validates `day_boundary_mode` and computes
day/session identities for 5m range sources, pivot confirmations and
strategy-candle alerts. Symbol mode currently registers BTCUSD with
a 24/7 UTC chart-day convention; custom sessions are explicit configuration,
not scraped exchange schedules. Legacy JSON defaults to IST calendar days.
\n### Contract expiry and session controls (cache 174)\nVerified Delta expired-product option settlement payoffs and optional account-margin audit CSV are loaded from selected datasets by `settlement.py`; their file fingerprints invalidate backtest cache. `engine.py` closes at expiry only with matching settlement data. `risk.close_at_session_end` is opt-in, closes with a valid pre-expiry option quote at last eligible strategy candle. Audit snapshots are read-only comparisons and cannot replicate Delta's portfolio risk engine.\n
### V175 broker observed risk history
backend/app/broker_history.py replays validated historical portfolio-margin captures and actual forced fills for diagnostics only. Missing periods remain unknown. These records are never used to liquidate hypothetical options or rewrite backtest P&L. Broker CSVs enter cache fingerprints.

### BTCUSD perpetual futures backtests
`StrategyConfig.market_type` defaults to OPTIONS. FUTURES dispatches from `engine.run_backtest` to `futures_engine.run_futures_backtest`; `data_store.preflight` requires only underlying OHLCV, not option instruments or quotes. The futures engine uses completed indicator/rule signals, dedicated risk/fees/funding configuration and research-only fills, and persists standard storage artifacts. Frontend selects the market using `FuturesSettings.tsx`; `Results.tsx` labels futures-specific limitations. Futures results have a separate cache key incorporating futures funding CSV fingerprints. Full specs: `FUTURES_BACKTEST.md`.

### Current futures research modules (milestones 1–6)
- `futures_contract.py`: current published BTCUSD contract snapshot, optional margin-tier research math.
- `futures_engine.py`: OHLC-proxy positions/fees/funding and estimated candle-close equity.
- `futures_validation.py`: frozen train/holdout with stressed holdout, `/api/research/futures-validation`.
- `futures_audit.py`: internal chart/entry/marker/fee parity audit, `/api/research/futures-parity-audit`.
- `research.py`: futures-specific execution replay, `/api/research/execution-replay`.
- `frontend/src/components/ReplayResearchPanel.tsx`: UI for those three jobs.
- `ai_prompt.py`: dynamically emits schema-15 importable JSON instructions. `examples/btcusd-futures-research.template.json` provides a static importable sample.

None of these confirms historical executable order-book quotes, portfolio risk, INR collateral conversions or guaranteed returns.
