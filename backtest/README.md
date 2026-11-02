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

## Legacy research captured-quote spool

The maintained `backtest.ema_vwap_research.run_dataset` now accepts
`quote_capture_storage="SQLITE"`, `quote_spool_directory=Path(...)`,
`quote_batch_size=4096`, and `max_captured_quotes=...`.
This stores the captured per-event option quotes on disk while retaining ordering,
indexing, and reverse iteration for the original execution logic. The historical
CSV is scanned once; no fabricated market quotes are introduced. The default
`MEMORY` remains unchanged. SQLite spools are removed after the run, including
on execution errors. Be aware the event dictionary, indicator DataFrame, and
output trade list still occupy RAM; this does not guarantee 1 GB VPS capacity.

For an actual **local historical archive** comparison (without downloads):

```powershell
python -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/YOUR_SEGMENT `
  --start 2026-09-01T00:00:00Z --end 2026-09-02T00:00:00Z `
  --output backtest/reports/legacy-quote-benchmark
```

This uses the original fixed H6 research scenario in independent processes with
`MEMORY` and `SQLITE` quote-capture modes. It writes trade-result parity,
execution times and Linux peak process RSS to `benchmark.json`. It fails if
trades or metrics differ. No live order placement or market data download.
Results depend on the local dataset and do not establish universal VPS memory
limits. SQLite reduces event-quote residency but creates disk I/O and can be
slower than RAM for smaller tests.

## Efficient quote/event scanning (optional)

The original `run_dataset` quote capture implementation is still the default
(`quote_capture_algorithm="LEGACY"`). The new `"SWEEP"` algorithm maintains
a time-ordered set of active event windows per option symbol, avoiding repeated
checks against already-expired events. It requires input CSV rows to be globally
nondecreasing by timestamp, and **fails closed** on out-of-order input rather
than silently sorting or changing fill order. Select
`quote_capture_storage="SQLITE"`, `quote_capture_algorithm="SWEEP"`,
and optionally `max_active_events=...` to combine disk-backed captured
quotes with bounded active-signal lookup. This is still a research-only data
model with synthetic bid/ask for public history.

`python -m backtest.benchmark_legacy_run` now compares the existing
`MEMORY+LEGACY` behavior with `SQLITE+SWEEP` using independent processes;
it rejects trade/metric differences. No real full-archive memory benchmark was
executed during this change, and retained indicator DataFrames/results remain
unbounded unless their existing admission limits are configured.


## Optional reduced decision-log retention

`backtest.ema_vwap_research.run_dataset(..., retain_decision_events=False)`
omits detailed signal/execution decision events from the returned report and
avoids retaining those diagnostic event dictionaries during the run. The
default remains `True`, preserving existing reports and all rejection counts,
trades, metrics, and entry/exit decisions. Use this opt-in mode only where
individual decision-event audit trails are not required.

This is a **partial** memory optimization: indicator DataFrames, option
instrument metadata, selected signal events, trade results and execution
attempts remain resident in memory. It does not establish bounded total RSS,
nor does it guarantee operation on a 1 GB VPS. Verify any resource benefit
against an actual local archive, without downloading new market data.
