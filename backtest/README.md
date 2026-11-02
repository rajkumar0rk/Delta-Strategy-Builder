# Backtest Engine

The current engine is a deterministic Python research runner for BTC options.
Its primary interface is `backtest.manual_combination`.

## Run A Scenario

Edit `backtest/config.manual-combination.toml`, then run:

```powershell
.\.venv\Scripts\python.exe -m backtest.manual_combination
```

To choose an output name:

```powershell
.\.venv\Scripts\python.exe -m backtest.manual_combination `
  --output my_scenario
```

If that folder exists, the runner creates `my_scenario_v2`, then `_v3`, and so
on. Each scenario contains `results.md`, `summary.json`, `monthly_summary.csv`,
and `trades.csv` where applicable.

The configuration supports:

- BT1, BT2, and BT3 strategy families.
- Baseline, ZigZag-style pullback, and momentum-breakout entries.
- Plain and all-fail exits with configurable EMA rules.
- MACD, H6, fee-aware, M30, Stoch momentum, volume, VWAP displacement, EMA
  strength, DTE, session, and weekday filters.
- Optional early-failure exits and profit protection.
- Full-BBO and size-aware execution assumptions.
- Public-history or imported R2-session data.

See `MANUAL_COMBINATIONS.md` for every configuration field.

## Historical Data

The canonical public archive is `backtest/data/delta-history`. Inspect it with:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive status
```

Append completed dates through yesterday:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync --through-yesterday
```

Download one completed month:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync --month 2026-11
```

R2 credentials belong in `.env`. Download and normalize one date with:

```powershell
.\.venv\Scripts\python.exe -m backtest.recorded download `
  --date 2026-09-23 `
  --output backtest\downloads\r2
```

The manual runner does not download R2 data automatically.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The maintained suite covers calculations, manual combinations, public-history
aggregation, archive behavior, execution assumptions, and BT1-BT3 logic.

## Important Limits

Public option bid/ask values are reconstructed estimates. A positive result can
also be dominated by a single exceptional option move. Always report execution
fidelity and rerun summaries without the largest winner before drawing a
conclusion.

## Legacy scalability controls (November 2026)

The original historical CSV reader is streaming at the file level and no longer
constructs a second full list before date filtering. The legacy simulator still
materializes the selected bars, option specifications and quotes as typed tuples.
A caller can pass `max_quote_rows` to `backtest.data.load_dataset` for explicit
admission control; omitted means unrestricted (backward compatible).

For free Delta public archive sync:
```powershell
python -m backtest.history_archive sync --through-yesterday `
  --download-workers 1 --api-max-attempts 4 --api-retry-base-seconds 0.5
```
Existing defaults are unchanged (4 workers, 4 HTTP attempts). Lower worker
count is preferable on a small VPS. Downloader quote data from public candles
remains **synthetic**, not observed historical bid/ask liquidity.

Check streaming CSV overhead without downloading any data:
```powershell
python -m backtest.benchmark_legacy_csv `
  --path backtest/data/delta-history/segments/YOUR_SEGMENT/option_quotes.csv `
  --max-rows 100000
```
This reports traced Python allocations for the scan, not a complete backtest's
resident memory. Frozen OHLCV/market-context hypotheses remain unchanged; the
original scientific results must not silently drift. Full-archive CPU/RSS
benchmarking has not been performed.

## Legacy dataset memory and parity (second pass)

`backtest.data.load_dataset(..., quote_storage="SQLITE")` now optionally
writes selected option quotes into a temporary on-disk SQLite spool instead of
keeping them as a tuple. Default remains `MEMORY` for compatibility.
Use `quote_spool_directory=Path(...)`, `quote_batch_size=4096`, and
`max_quote_rows=...` for resource admission. Keep the dataset alive while
reading quotes, then call `dataset.quotes.close()` to remove temporary files.
This is a quote loader API; legacy scenario runners do not automatically switch
to it, and full-memory savings for end-to-end simulations are not yet measured.

The frozen OHLCV and market-context discovery tools preserve their original
thresholds. Set `DELTA_DISCOVERY_MAX_INPUT_MB=100` to reject an oversized
input file before Pandas loads it; zero (default) means unlimited.
This is a file-size guard, **not** streaming Pandas processing.

To check a saved baseline and refactored report without re-downloading data:
```powershell
python -m backtest.compare_legacy_reports --baseline baseline.json --current current.json
```
Comparison ignores generated timestamps/paths but fails on changed trade
records, numeric metrics and source strategy parameters. Capture baseline
reports **before** changing historical engine behavior. No actual large
archive benchmark or before/after report pair was available to validate this
feature during implementation.
