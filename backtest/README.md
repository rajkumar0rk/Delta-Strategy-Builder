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


## Indexed SQLite event-quote replay (opt-in SQLite capture)

SQLite-backed `EventQuoteView` now uses a per-event quote-position index for
direct integer access, rather than skipping rows using `OFFSET`. Slices,
including reversed and stepped slices, use one ordered indexed query rather
than one query per element. Event quote values, ordering and the default
`MEMORY` capture mode are unchanged. Existing event-local SQLite spools are
temporary and recreated for each run; no permanent database migration needed.

This improves random-access query complexity but does not establish a
measured end-to-end speedup or full historical streaming. Benchmark on your
laptop's existing archive before claiming gains. No historical downloads.

## Opt-in collection admission limits


`run_dataset(..., resource_limits=LegacyResourceLimits(...))` accepts
`max_underlying_bars`, `max_option_instruments`, `max_scenarios`,
`max_signal_events`, `max_decision_events`,
`max_execution_attempts`, and `max_trades`. Import
`LegacyResourceLimits` from `backtest.resource_limits`.

Each limit is an optional positive integer; `None` (default) preserves
existing behavior. When exceeded, research raises a descriptive
`LEGACY_*_LIMIT_EXCEEDED` error instead of dropping trades, events or
source records. A shared decision-event budget counts underlying signal
and execution decisions once, even when a configuration's decisions are
replicated across scenario reports. Set `retain_decision_events=False`
to omit those detailed diagnostics entirely.

These controls bound *admitted collection counts*, not total process RSS.
The underlying Pandas CSV is still fully materialized before its row
limit is checked, and event and report collections may temporarily grow
before a post-generation limit rejects them. Large datasets therefore
still require true streaming and independent peak-RSS benchmarks.


## Laptop-first process-memory benchmark (Windows and Linux)

The offline `backtest.benchmark_legacy_run` command now reports peak process
memory on Windows (PeakWorkingSetSize) and Linux (ru_maxrss) in KiB, under
`measurements[...].peak_process_rss_kib`. Each capture mode runs in its own
process, preserving the existing report-parity comparison. Other operating
systems may report null. To benchmark without detailed decision logs, add
`--omit-decision-events`; it applies identically to both capture modes,
and the original default still retains diagnostics.

Example on your Windows laptop (no downloads):

```powershell
python -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/YOUR_SEGMENT `
  --start 2026-09-01T00:00:00Z --end 2026-09-02T00:00:00Z `
  --output backtest/reports/laptop-legacy-benchmark `
  --omit-decision-events
```

Use a locally available folder containing `underlying_bars.csv`,
`option_instruments.csv`, and `option_quotes.csv`. The tool does not
automatically resolve catalog segments. Results remain research-only and
are **not** proof of parity on the full archive until run on your data.


## Optional instrument window pruning

`backtest.ema_vwap_research.run_dataset(..., prune_inactive_instruments=True)`
streams `option_instruments.csv` and retains only contracts that could have
been active at some point in the requested [start, end) signal period.
Contracts which expired on/before `start`, or activated on/after `end`,
cannot be selected and are omitted. This avoids repeatedly checking
irrelevant older/future instruments during each signal's option selection.
The default remains `False` for backward compatibility. The option
selector itself (DTE, expiry, direction, and nearest strike) is unchanged,
and parity tests compare both modes over synthetic time windows.

`LegacyResourceLimits(max_option_instruments=...)` is now enforced while
the instrument rows are processed, before the selected list grows past its
configured limit. A too-large run fails rather than truncating records.
This is not a fully streaming Pandas indicator engine, and actual speed and
memory improvements require benchmarks against your laptop's local archive.


## Three-profile laptop validation (no data downloads)

After pulling `working`, use this command on any **existing local**
normalized dataset containing `underlying_bars.csv`,
`option_instruments.csv`, and `option_quotes.csv`:

```powershell
python -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/YOUR_SEGMENT `
  --start 2026-09-01T00:00:00Z --end 2026-09-02T00:00:00Z `
  --output backtest/reports/three-profile-benchmark `
  --include-pruned-profile --omit-decision-events
```

The three independent runs are `MEMORY+LEGACY`, `SQLITE+SWEEP`,
and `SQLITE+SWEEP+prune_inactive_instruments`. Results and per-mode
differences are retained in the output directory, with per-process elapsed
seconds and peak RSS in `benchmark.json`. A difference fails closed.
The optional omission of detailed diagnostic events applies to **all**
profiles equally. Omit that switch to test full diagnostic output parity.
This benchmark executes the original frozen H6 research configuration and
does not verify arbitrary Strategy Lab JSONs, live fills or margin.
For reliable comparisons, run one segment at a time, ensure sufficient
disk space, and repeat runs to account for OS caching.


## Opt-in stateful core indicator CSV processing

The original EMA/VWAP research runner accepts
`run_dataset(..., indicator_chunk_rows=50000)`. This processes raw source CSV
batches in order, maintaining EMA9/20/50, Wilder RSI14, ATR14, MACD and
MACD-signal state across chunk boundaries. Standard Pandas Stoch RSI, rolling
volume median, session VWAP and downstream signal calculations still run on
the resulting retained DataFrame to preserve historical semantics.

Unset `indicator_chunk_rows` retains the original indicator path. The
streamed option rejects out-of-order timestamps rather than sorting the
source and silently changing causal indicator state. This is **incremental
core-indicator computation**, not fully bounded-memory backtesting: selected
bars and derived signals are still retained for research. Manual full-archive
trade/report parity and peak-RAM measurements are required before selecting
this mode as a default.


### Verify full report parity for stateful indicators on the laptop

Run the existing offline benchmark with an additional streamed-indicator
profile. All profiles use identical locked research scenarios; the streamed
profile uses the same SQLITE+SWEEP quote capture and a configured CSV batch
size, but replaces the core indicator preparation.

```powershell
python -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/YOUR_SEGMENT `
  --start 2026-09-01T00:00:00Z --end 2026-09-02T00:00:00Z `
  --output backtest/reports/indicator-parity `
  --indicator-chunk-rows 50000
```

Any report/trade mismatch fails closed; the benchmark records elapsed
time and per-process peak RSS. Use a valid local normalized historical
segment, not the archive catalog root. The command does not download data.


## Indexed in-memory contract selection (opt-in)

`run_dataset(..., indexed_option_selection=True)` constructs a reusable
index of available option expiries grouped by CE/PE once per research run.
Signals search relevant expiries rather than scanning every historical
instrument. The earliest eligible expiry and stable nearest-strike
tie-break are unchanged. The default remains the legacy linear scan.

For an isolated speed and complete report-parity check on your local archive:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/YOUR_SEGMENT `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/indexed-memory-parity `
  --include-indexed-profile
```

This adds `MEMORY_INDEXED` to the unchanged original MEMORY and SQLITE
profiles. If the trading reports differ, the command fails. CPU/RAM benefits
depend on instrument count and actual qualifying signal frequency. The index
does not change historical execution assumptions or guarantee a speed gain.


## CPU hotspot profiling on an existing laptop dataset

The new offline profiler executes the original locked H6 scenario using
the default MEMORY+LEGACY path with Python `cProfile`. It writes
`cpu.pstats` (full function call graph) and `profile.json` (ranked
cumulative CPU functions, stage timings, trade counts, execution attempts
and peak process RSS). `--track-allocations` additionally records traced
Python allocations, at a potentially substantial speed cost.

```powershell
.\.venv\Scripts\python.exe -m backtest.profile_legacy_run `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/legacy-cpu-profile
```

No market data is downloaded. Profiling overhead means these timings are
**not** directly comparable with non-profiled benchmark durations. The
tracemalloc optional metric excludes native allocations of NumPy/Pandas;
use reported Windows peak process working-set for overall observed RAM.
Before optimizing a subsystem, inspect whether actual trades and signals
were present. This research CLI does not place orders or validate broker
fills. The normal `run_dataset` report remains unchanged.


## Phase 1: positional quote CSV parser (opt-in)

Profiling an actual seven-day local H6 research dataset identified historical
option quote CSV reading as the largest stage. The legacy research runner can
now select `run_dataset(..., quote_csv_parser="POSITIONAL")`, which resolves
the header once and uses `csv.reader` instead of creating a dictionary for
every quote row. The original `DICT` parser is still the default. Both
`LEGACY` and `SWEEP` quote-capture algorithms support this independent
parser setting.

Benchmark exact trade/report parity and actual runtime before changing defaults:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/positional-quote-parity `
  --include-positional-profile
```

This runs original `MEMORY`, `SQLITE` and `MEMORY_POSITIONAL`
independently, compares their complete report content and records process
memory/time. Matching reports do not prove the optimized code is faster;
only repeated measurements on local historical data can establish a gain.
No market data is downloaded.


### Alternating parser A/B benchmark

For an order-balanced test instead of fixed-order repeats, use the standalone
offline A/B benchmark. It runs four independent MEMORY+LEGACY child processes
per round using the alternating sequences DICT/POSITIONAL/POSITIONAL/DICT and
POSITIONAL/DICT/DICT/POSITIONAL. All complete reports are checked against
the first DICT report before timings are summarized.

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/positional-ab `
  --rounds 3
```

The saved benchmark.json includes individual runs, medians, mean times,
trade counts, peak memory, and parity differences. The original DICT parser
remains the default until this and longer-period tests justify promotion.


### Default parser after historical A/B validation

The original EMA/VWAP legacy research `run_dataset` now defaults to
`quote_csv_parser="POSITIONAL"` for faster normalized option-quote CSV
processing. Set `quote_csv_parser="DICT"` explicitly to restore the original
per-record dictionary reader. Existing trading rules, fees, quote capture
algorithms and storage modes are unchanged. The independent benchmark
continues to use **DICT** for its original MEMORY and SQLITE baseline
profiles, and POSITIONAL for the comparison profile, even after the
production default changes. This change does not apply to the general
Strategy Lab JSON backtest engine.
