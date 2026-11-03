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


### Four-way parser + candle lookup validation

A previous `MEMORY_BAR_LOOKUP` benchmark accidentally passed both POSITIONAL
and candle lookup while labeling its CSV parser DICT. The corrected benchmark
now separates DICT, POSITIONAL-only, DICT+bar lookup, and combined
POSITIONAL+bar lookup, and records the **actual** parser for each profile.

```powershell
.\\.venv\\Scripts\\python.exe -m backtest.benchmark_legacy_run \`
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 \`
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z \`
  --output backtest/reports/combined-bar-parity \`
  --include-positional-profile --include-bar-lookup-profile \`
  --include-combined-profile
```

Do not promote bar lookup based on previous incorrectly labeled timing; compare
`MEMORY_COMBINED` against `MEMORY_POSITIONAL` and require full report parity.


### Compare POSITIONAL against combined candle lookup (balanced A/B)

The earlier combined benchmark returned matching reports but highly variable
runtimes. Use the same parser on both sides and vary **only** candle lookup:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/bar-lookup-ab `
  --comparison BAR_LOOKUP --rounds 3
```

ABBA/BAAB runs alternate POSITIONAL alone versus
POSITIONAL+positional_bar_lookup. Each run compares its **complete** report
against a freshly captured POSITIONAL baseline, including the actual trade
list and fees. The original  `QUOTE_PARSER` comparison remains available
and the default; no backtest runtime settings are changed.


### Promoted positional candle lookup

The locked H6 research runner now defaults to both `quote_csv_parser="POSITIONAL"`
and `positional_bar_lookup=True`. In 12 alternating, independent-process local
trials, median duration dropped from 13.03 s to 10.97 s (15.77%), with
922 trades, 952 execution attempts and identical full reports across every
trial. To restore original candle-window semantics explicitly, call
`run_dataset(..., positional_bar_lookup=False)`. To restore the original
quote parser too, set `quote_csv_parser="DICT"`.

The AB comparison command continues to *explicitly* force the flags in
its child processes and therefore still compares the original POSITIONAL
baseline to the combined mode after this promotion. This default applies
to legacy EMA/VWAP research only, **not** the JSON Strategy Lab engine.
Memory gains were small; bounded-memory execution is not yet implemented.


### Bounded captured-quote storage: optional packed SQLite spool

For large legacy EMA/VWAP research runs, `quote_capture_storage="SQLITE"`
spools captured event quotes to a temporary SQLite file instead of keeping
all captured quote dictionaries in RAM. Writer batches are bounded by
`quote_batch_size` (default 4096). This bounds the *quote writer batch*,
not total process memory: underlying indicator DataFrames, signal events,
and the returned trade/decision report remain in RAM.

New: `quote_spool_encoding="PACKED"` stores the exact seven normalized
quote floats in a 56-byte binary record (plus SQLite overhead), instead
of a JSON string. Original `quote_spool_encoding="JSON"` remains the
default and is the fallback. PACKED is only supported for the fixed seven
fields emitted by the historical quote capture pipeline; unknown/missing
fields fail closed. The spool is cleaned up on normal completion and
exceptions. `max_captured_quotes` can still fail closed on exceeding
the configured quota; it does not silently truncate records.

Run a complete-report correctness, CPU and RSS comparison on existing
local seven-day data, with identical POSITIONAL parser, optimized candle
lookup and SWEEP capture for both disk-backed variants:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_legacy_run `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z --end 2026-09-08T00:00:00Z `
  --output backtest/reports/packed-sqlite-parity `
  --include-combined-profile `
  --include-packed-sqlite-profile
```

Compare `SQLITE_POSITIONAL_JSON` against
`SQLITE_POSITIONAL_PACKED`; `MEMORY_COMBINED` is the fast in-memory
reference. No actual speed or RAM gain should be assumed until your local
results confirm it. This remains the locked H6 legacy research pipeline,
not the general Strategy Lab configurable JSON engine. It does **not**
provide globally bounded-memory historical backtests.


### Balanced A/B for packed SQLite and captured-quote disk footprint

For a controlled comparison of the two disk-backed formats, run:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-08T00:00:00Z `
  --output backtest/reports/packed-sqlite-ab `
  --comparison SQLITE_ENCODING --rounds 3
```

This runs 12 independent child backtests in ABBA / BAAB order. Both variants
use SQLite+SWEEP quote capture, the POSITIONAL quote CSV parser and positional
candle lookup; only JSON/PACKED storage differs. All trade, fee, execution,
decision-event and diagnostic reports are compared against the first JSON
reference. `benchmark.json` includes per-run `quote_spool_metrics`:
`captured_quote_rows`, `event_count`, `writer_batch_size`,
`peak_pending_rows`, `sqlite_disk_bytes` and `sqlite_pages_bytes`.
Disk usage includes SQLite table/index overhead and is measured before
temporary spool cleanup, not after.

To investigate scaling, repeat the test on a longer *existing* local
history range with sufficient option coverage; do not infer bounded total
RSS from the seven-day test alone. The full indicator DataFrame, scenario
events and final report are still materialized in memory. This does not
run on the general configurable JSON strategy engine. JSON encoding and
fast in-memory quote storage remain unchanged defaults.


### Phase 1 — inspect memory growth before introducing streaming indicators

The H6 research runner can now emit an opt-in retention inventory. The
diagnostic records indicator DataFrame rows and bytes, option instrument
counts, signal events, captured quote rows, execution attempts, trades,
and retained decision events, plus **cumulative peak process RSS** at each
major phase. This instrument is outside the report, so trade and fee parity
can still be checked. Stage peaks are cumulative, not instantaneous working
set samples.

Use the independent-process multi-window benchmark on existing data:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_memory_growth `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --days 1,7,14 `
  --output backtest/reports/memory-growth
```

Runs each horizon separately for the fast MEMORY+POSITIONAL+bar lookup path
and for PACKED SQLite+SWEEP+POSITIONAL+bar lookup; checks the complete
reports at matching horizons. All quote files are read locally, without
downloading historical data.

**Important:** the legacy `indicators()` loader currently materializes the
entire `underlying_bars.csv` file before applying signal date constraints.
A one-day strategy window may therefore retain the same indicator frame as
a 14-day window. Inspect `indicator_rows` and `indicator_frame_bytes`
rather than claiming range-level memory proportionality or globally bounded
RSS. Next step is deciding whether to change full-frame indicator ownership,
and how much warm-up state must be preserved to maintain exact parity.


### Opt-in release of completed signal configurations

The memory-growth inventory showed that while the source indicator frame stays
at 8,790 rows (3.96 MiB), in-memory signal quotes grow from 2,030 to
31,988 between 1-day and 14-day backtests. The research runner can now
set `run_dataset(..., release_completed_configurations=True)` to release
each configuration's captured quote lists, signal objects and original
configuration decision list **after its last consuming scenario finishes**.
Shared configurations are never released before all their scenario consumers
finish. Signal counts are snapshotted so the returned report remains byte-
and value-equivalent to the original after JSON serialization.

The default remains `False` until a real-archive test shows unchanged trade,
fee, execution-attempt and decision reports and a useful peak-RAM reduction.
Neither trading rules nor entry/exit semantics change. This is incremental
retention reduction, **not** globally bounded-memory execution: quotes must
still be retained until their last consumer, and all final report records
remain materialized.

Measure the effect with a balanced 12-run A/B test comparing current
POSITIONAL+bar lookup against the same execution with release enabled:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/retention-ab `
  --comparison RETENTION --rounds 3
```

The 14-day window is preferred because it captured 31,988 quote rows and
1,867 trades. Review median process RSS and runtime and require full-report
parity before promoting the setting. For larger history, the materialized
indicator DataFrame and final reports remain separate scaling problems.


### Default post-signal simulation frame reduction (legacy H6)

The full indicator candle frame must still be calculated before signals,
because EMA/RSI/ATR smoothing and session VWAP depend on prior history, and
because signal decision diagnostics are sensitive to the original timeline.
After all signal configurations have been evaluated,
`run_dataset` now defaults to `trim_simulation_frame=True`: it retains
only simulation-used columns and preceding candle lookback needed for
early-failure structure levels and directional confirmation. It keeps
*all* future candles for holds without a fixed deadline. Restore original
full-frame behavior explicitly with `trim_simulation_frame=False`.
The new default was promoted after the user's 12-run ABBA/BAAB test
(September 1–15, 2026): complete-report parity across 1,867 trades
and 1,903 execution attempts; median runtime 20.61s → 17.73s
(13.97% lower) and median peak process RSS 96.63MiB → 94.72MiB
(approximately 1.90MiB lower).

This is **not** a streaming indicator loader: the full source still reaches
its initial peak while indicators are being built. The feature targets the
later quote capture / trade simulation peak by freeing the no-longer-needed
historical frame blocks. Frame reduction is bypassed safely for unsupported
index/order/column shapes.

Re-run the frozen A/B benchmark against the original POSITIONAL + candle
lookup **untrimmed baseline**, with 12 independent order-balanced runs
and full trade/fee/decision-report parity. The benchmark explicitly pins
both variants, so changing the runner default does not invalidate it:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/frame-trim-ab `
  --comparison FRAME_TRIM --rounds 3
```

The change applies to the legacy research runner only, not the configurable
JSON strategy engine. The indicator loader still materializes all source
candles before frame trimming, and final trade/decision reports still grow
with history. Full bounded-memory execution remains unimplemented.


### Compact categorical direction columns (opt-in legacy indicator memory)

The legacy `indicators()` implementation creates six direction columns with
only three possible values: `""` (flat), `CALL`, or `PUT`. The opt-in
`compact_directions=True` represents these fields as Pandas categoricals
instead of storing a repeated Python string per row. CALL/PUT calculations,
numerical EMA/RSI/ATR/MACD/Stoch RSI/VWAP values, all entry signal booleans,
and the underlying input columns remain unchanged.

For the legacy `run_dataset` pipeline, enable
`compact_indicator_directions=True` to create compact columns during
indicator construction. The default is **False** pending historical-report
parity and peak-RSS measurements. This option also works with the existing
`indicator_chunk_rows` mode, which persists EMA/RSI/ATR/MACD state across
input batches, but still concatenates the complete frame.

To compare the current POSITIONAL + candle lookup + simulation trim default
against *only* categorical direction storage (12 order-balanced runs):

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_positional_ab `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/indicator-compact-ab `
  --comparison INDICATOR_COMPACT --rounds 3
```

Check both exact report parity and peak-RSS reduction before considering a
default change. This improves repeated categorical storage, but is **not**
bounded-memory indicator streaming: the entire source candle file still
materializes, and the final report remains in memory.


### Phase 1 — identify the dominant retained Python allocations

The 14-day H6 `INDICATOR_COMPACT` test preserved 1,867 trades and 1,903
execution attempts across 12 runs, but reduced median runtime only ~1.41%
and increased median process RSS ~222 KiB. Categorical compression therefore
remains opt-in. The next task is to **measure actual retained allocations**
before implementing further memory changes.

The existing offline legacy profiler now supports per-stage Python allocation
deltas, instantaneous process RSS, cumulative process peak, and estimated
retained Python object bytes in each final-report field:

```powershell
.\.venv\Scripts\python.exe -m backtest.profile_legacy_run `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/retained-allocation-profile `
  --track-allocations
```

Review `profile.json`: `stages[].current_process_rss_kib`,
`stages[].cumulative_peak_process_rss_kib`,
`stages[].python_traced_current_bytes`,
`stages[].python_allocation_changes` (source file and line),
`retention_inventory`, and
`report_retained_python_bytes.total_unique_python_bytes` and `.fields`.

**Limitations:** cProfile and tracemalloc introduce substantial overhead;
do not use the profiled runtime or RSS as a normal backtest speed benchmark.
Tracemalloc does not account for every native Pandas/NumPy buffer or allocator
fragmentation. Per-report-field byte counts are separate estimates that may
overlap due to shared Python objects; do not sum them. This is diagnostic only:
no changes to indicators, trading decisions, configuration defaults, or
strategy output. Full bounded-memory historical backtesting still remains
unimplemented, and this is legacy H6 only, not the JSON strategy engine.


### Opt-in lossless incremental H6 report records

The 14-day allocation profile shows approximately 12.02 MiB of retained
Python report objects (8,190 decisions, 1,867 trades and 1,903 execution
attempts) while the indicator frame after trimming is approximately 0.68 MiB.
To avoid accumulating **all scenarios' aggregate** report records in RAM,
the legacy runner now has a separate API:

```python
from pathlib import Path
from backtest.ema_vwap_research import (
    run_dataset_to_streamed_report, locked_h6_scenarios,
)

manifest = run_dataset_to_streamed_report(
    Path("backtest/data/delta-history/segments/2026-08-24_09-22"),
    start="2026-09-01T00:00:00Z",
    end="2026-09-15T00:00:00Z",
    output=Path("backtest/reports/streamed-report.json"),
    scenario_set=locked_h6_scenarios(),
)
```

It writes trades, execution attempts, and decision records to bounded-writer
append-only temporary JSONL files as they are produced. At successful
completion it assembles the **complete original-shape JSON report** without
loading all those records back into Python lists, and atomically replaces
the destination only after successful serialization. A failed write
preserves any existing report; temporary files are cleaned up. The API
returns a small manifest with file path, bytes and record counts. Ordinary
`run_dataset()` still returns its exact original Python dictionary and lists;
this new API is explicitly opt-in. Normal defaults, safety checks and
trading logic are unchanged. Report fields are never silently truncated.

Benchmark the default in-memory report versus streamed report output,
including writing the complete JSON file **on both sides**, in independent
order-balanced subprocesses:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_report_streaming `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/report-streaming-ab `
  --rounds 3
```

Benchmark comparison uses zero numeric tolerance and checks the complete
report, including fees/GST and all decision records. Peak process RSS
includes report output on both sides; the timing includes the disk I/O.
Do not assume reduced RAM or improved speed until local results are known.
This remains **partially bounded**: per-scenario trade metrics, source
indicators, signal configurations, captured quotes and other report metadata
are still in memory. It is not integrated into the general JSON Strategy
Lab engine and is not full streaming execution.


### File-oriented locked H6 reports with low-memory exports

The 14-day 12-run ABBA/BAAB historical report benchmark verified zero
trade/fee/decision report differences (1,867 trades; 1,903 execution attempts;
8,190 decisions), with median peak RSS dropping from 124,442 KiB to
88,304 KiB (**35.29 MiB / 29.0% less RAM**) and median runtime increasing
from 25.70 seconds to 26.71 seconds (3.9%).

For complete summary.json and the existing trades.csv, execution_attempts.csv
and decision_events.csv outputs, use the new file-oriented legacy H6 command:

```powershell
.\.venv\Scripts\python.exe -m backtest.export_legacy_report `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/locked-h6-streamed `
  --storage STREAMED
```

This new exporter defaults to STREAMED storage and retains a reversible
`--storage MEMORY` option for original report generation. CSV records and
headers are emitted through temporary append-only JSONL storage and
published atomically *per file* without materializing each complete
aggregate list, preserving the historical output field order and rows.
JSON and each CSV are individually atomic, not a transaction spanning
the whole output directory; readers should only consume after the command
exits successfully. Existing in-memory `run_dataset()`, the legacy matrix
research CLI and the configurable JSON strategy engine are unchanged.

For a custom temporary scratch location add
`--spool-directory backtest/reports/tmp-spool` (STREAMED only). The
temporary spool is removed when export completes or raises. Allow adequate
disk space for intermediate files and full reports; this is **not** a
hard ceiling on total process memory because per-scenario trades, source
indicators and signal/quote events are still in memory.


### Phase 1 — opt-in lossless packed in-memory captured quotes

The H6 runner now accepts `run_dataset(...,
quote_capture_storage="PACKED_MEMORY")`. This stores each selected option
quote as precisely seven little-endian IEEE-754 doubles (56 bytes) in
per-event in-memory byte arrays rather than retaining a dictionary per
captured quote. Quotes are decoded to the *same* seven-field dictionaries on
indexed access, iteration or reverse iteration. The quote payload is not
rounded or truncated. Existing `max_captured_quotes` limits fail closed;
unknown payload schemas raise an error.

The default `quote_capture_storage="MEMORY"` is unchanged, as is the
existing `SQLITE` alternative (with JSON or PACKED disk format). Packed
in-memory quotes do not remove the need to hold signal events, indicator
frames or the final report. It is **not** a fully streaming quote-processing
engine, nor an end-to-end memory cap. The mode is experimental until
controlled archive results show complete report parity and a useful peak
RSS/runtime tradeoff.

Compare the packed in-memory quote storage with ordinary Python dictionary
quote storage while **holding streamed report output constant**:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_report_streaming `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/packed-memory-quotes-ab `
  --comparison QUOTE_STORAGE --rounds 3
```

Both variants use the same POSITIONAL quote CSV parser, LEGACY capture
algorithm, positional bar lookup, trimmed simulation frame, and opt-in
lossless streamed complete-report writer. The balanced 12-run benchmark
compares every JSON field and fee/decision result at **zero** numerical
tolerance, and reports wall time and process peak RSS independently. The
original `REPORT_STORAGE` comparison remains available as the default.
This is the locked H6 research path, not the configurable Strategy Lab
JSON engine.


### Promoted packed quote storage for the file-oriented locked H6 exporter

On the 14-day local archive, 12 independent `QUOTE_STORAGE` benchmark
executions verified **zero complete-report differences**, including 1,867
trades, 1,903 execution attempts, 8,190 decision events and identical
9,380,701-byte report files. Median peak RSS fell from 88,294 KiB to
84,774 KiB (**3,520 KiB / 3.44 MiB / 3.99% less**). Median execution time
fell from 24.765s to 23.731s (4.17%), but per-run timing varied widely;
do not assume a dependable speed improvement.

Accordingly, the *new* `python -m backtest.export_legacy_report`
file-oriented locked H6 exporter now defaults to both
`--storage STREAMED` and `--quote-storage PACKED_MEMORY`. The JSON and
legacy CSV outputs retain the original content and fields. To keep streamed
reports but restore original in-memory quote dictionaries, add:

```powershell
--quote-storage MEMORY
```

To restore the complete original report-and-quote memory mode, use
`--storage MEMORY` (which automatically uses dictionary quotes).
The export command prints the selected `quote_storage` in its manifest
for auditing. Unlike this *specific* export command,
`run_dataset()` continues to default to
`quote_capture_storage="MEMORY"` and returns a complete Python report
dictionary. The existing matrix research CLI and general JSON Strategy
Lab engine have **not** changed. This optimization alone is not
fully bounded-memory streaming: indicators, signals, and scenario trade
metrics remain retained.


### Phase 1 — bounded indicator-only chunk iterator (experimental)

The initial legacy indicator engine still builds a full historical DataFrame.
The new `backtest.legacy_full_indicator_stream.iter_complete_indicator_chunks`
is an **opt-in** bounded-memory iterator that generates the complete H6
indicator schema from sequential CSV chunks without concatenating them.
It preserves recursive EMA9/20/50, Wilder RSI14, ATR14, MACD/signal, and
calculates Stochastic RSI K/D, prior-20-volume median, IST session VWAP,
six CALL/PUT direction fields and all six entry/crossover flags.

It carries the current IST VWAP session plus 20 preceding source bars to
preserve rolling calculations and entry-state continuity. The maximum
working context is explicitly bounded by `chunk_rows + max_session_rows +
20` rows (with a configurable fail-closed per-session limit, default 4096).
Timestamps must be timezone-aware, in chronological order. No candles or
decision records are silently dropped, reordered or rounded. Numeric
parity is checked using the same tight tolerance as the existing streamed
core indicators, and direction/entry flags are compared exactly.

```python
from pathlib import Path
from backtest.legacy_full_indicator_stream import iter_complete_indicator_chunks

for frame in iter_complete_indicator_chunks(
    Path("backtest/data/delta-history/segments/2026-08-24_09-22/underlying_bars.csv"),
    chunk_rows=512, max_session_rows=4096,
):
    # Consume each complete, indicator-enriched chunk and release it before
    # requesting the next. Do not concatenate chunks to retain the saving.
    print(frame.index[0], frame.index[-1], len(frame))
```

Benchmark complete indicator rows, all entry flags, process peak RSS and
execution time against the original full-frame baseline (12 independent
ABBA/BAAB runs, both modes write CSV outputs to account for I/O):

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_indicator_chunks `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --output backtest/reports/full-indicator-chunks-ab `
  --chunk-rows 512 --max-session-rows 4096 --rounds 3
```

The validator checks every output row, numerical fields with
`rtol=1e-10, atol=1e-9` and timestamps/directions/booleans exactly.
The benchmark is **indicator-only**. It does **not** claim final trade/fee
report parity, and the normal `indicators()` or `run_dataset()` APIs
have not switched to this generator. The next milestone is connecting
these complete chunks to genuinely incremental signal evaluation while
retaining exact decision diagnostics, shared-scenario event ordering and
unlimited-hold exit semantics. Until then, the full legacy backtest is
still not end-to-end memory-bounded. No changes to the general JSON
Strategy Lab engine or live trading.


### Fix: Stochastic RSI strict-comparison drift in bounded chunks

The first 12-run archive benchmark of the bounded H6 indicator iterator
failed parity: 180 *reported/capped* discrepancies, concentrated in
`direction_stoch`, `direction_macd_stoch`, and dependent entry flags
(e.g., source CSV rows 5389, 5705, 5980, 6226). Other near-identical
floating-point Stoch RSI K and D values can still flip a strict `K < D`
or `D < K` comparison if their rolling means restart accumulation at
batch boundaries. A 10,000-candle synthetic reproduction reproduced this
effect even when numeric values passed a tight tolerance.

The experimental `iter_complete_indicator_chunks()` path now keeps
Pandas-compatible compensated rolling-mean state **continuously across
all chunks** for both 3-bar Stoch RSI smoothers. Only the 14-bar RSI
normalization and rolling minimum/maximum use bounded overlap, while
the exact prior K/D values are carried for previous-row entry signals.
The original full-frame indicator calculation remains untouched.
Regression tests check the running mean against Pandas at exact
floating-point equality, plus long multi-day, strict Stoch entry parity.

Re-run the same `benchmark_indicator_chunks --chunk-rows 512`
historical archive comparison to validate **all rows and entry flags**
before connecting this generator to live signals or H6 trade execution.
No backtest results, exchange orders or general JSON strategy engine
settings have been changed by this fix. This is still an opt-in,
indicator-only iterator rather than full bounded-memory trading.


### Phase 1 — experimental incremental H6 BASELINE signals

The bounded full-indicator iterator passed a user-run 8,790-candle,
12-execution historical benchmark with zero indicator differences (including
strict Stochastic RSI entry signals), but was slower and used more *peak
process RSS* than full-frame indicators on that small data sample.
Do **not** replace the ordinary H6 execution path solely because an
indicator iterator retains fewer bars.

`backtest.legacy_incremental_signals.iter_incremental_baseline_signals`
is a new **opt-in signal-only generator**. It consumes completed indicator
chunks and tracks the previous direction, EMA-regime start, and a bounded
queue of pending confirmation candles. It yields one qualified signal at
a time, retaining no complete historical frame or signal list. The
`decision_events` argument accepts an append-only sink to preserve the
legacy signal decision/rejection reasons and their original order.

Only `entry_mode=BASELINE` with pullback and momentum-breakout modes
disabled is supported; `ZIGZAG`, `MOMENTUM` and `BOTH` explicitly
raise rather than silently using a different strategy. The generator
supports original MACD confirmation, 1/2/3 entry conditions, Stoch RSI
entry/momentum filtering, confirmation candles, UTC and IST entry
sessions, blocked weekdays, option expiry selection, and EMA regimes.
It does **not** change any existing runner entry point.

Benchmark the independent original full-frame
`signal_events()` reference against streamed indicator chunks and
incremental signal evaluation for both shared locked-H6 signal
configurations (MACD off/on) over the same archive:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_incremental_signals `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/incremental-h6-signals-ab `
  --chunk-rows 512 --max-session-rows 4096 --rounds 3
```

The 12 independent ABBA/BAAB runs write complete candidate and reference
signal/decision JSONL files, compare every signal timestamp (nanoseconds
exact), option selection, EMA regime start, event ordering, rejections and
decision diagnostics. Floating-point measurements compare with tight
`rtol=1e-10, atol=1e-9`; boolean and textual fields are exact.
They record median wall-clock time and peak process RSS. No live data
download, exchange trading or order placement occurs.

**Important limitations:** The general H6 `run_dataset()` still uses
its original full-frame signal path. This milestone is not integrated
into option quote capture/trade simulation; it does **not** establish
trade/fee/GST/execution/report parity, nor full end-to-end bounded memory.
The configurable JSON Strategy Lab is likewise unchanged. Full signal
benchmark parity must pass before incrementally connecting quote and
trade execution.


### Phase 1 — experimental streaming signal-to-quote journal

The user's 14-day locked-H6 A/B benchmark of incremental BASELINE signals
passed all 12 runs with **zero event/decision differences** (242 non-MACD
signals, 215 MACD signals, 908 signal decisions). Median peak RSS fell
from 86,092 KiB to 83,182 KiB (**2.84 MiB / 3.38%**), while median
runtime increased from 1.591s to 2.056s (**29% slower**). These figures
cover signal evaluation, not the entire backtest.

The next experimental building block,
`backtest.legacy_signal_quote_journal.StreamingSignalQuoteJournal`,
bridges the incremental `SignalEvent` generator to historical option
quote capture. Signal metadata is spooled to an indexed temporary SQLite
database with stable event IDs. A single pass of the original normalized
`option_quotes.csv` populates the existing packed-quote SQLite adapter;
later replay yields `SignalEvent` objects with order-preserving,
indexable, reversible quote sequences. The bridge supports shared signal
configurations, overlapping quote windows, duplicate quote rows and
unsorted quote timestamps (matching the original LEGACY positional capture
algorithm, not requiring the SWEEP monotonic assumption). Configurable
`max_signals` and `max_captured_quotes` limits fail closed; a partial
failed capture cannot be retried or replayed; temporary SQLite storage is
cleaned up after exit.

The existing `run_dataset` and `export_legacy_report` execution paths
are **not** switched to this journal. It does NOT yet populate option
true-range histories, change margin/funding assumptions, or execute any
trades. No fee/GST/exit/P&L parity is claimed.

Compare every quote for both locked-H6 BASELINE signal configurations
against original full-frame `signal_events()` plus
`capture_quotes_positional()`, using independent processes and a balanced
ABBA/BAAB design:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_signal_quote_journal `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/signal-quote-journal-ab `
  --chunk-rows 512 --max-session-rows 4096 --rounds 3
```

This writes `benchmark.json`, all reference event/quote JSONL records,
and the first 30 exact mismatch descriptions if any. It checks every
signal timestamp, option contract, direction, EMA regime and seven-field
ordered quote record with **zero numeric tolerance**, and compares captured
quote counts, elapsed time and peak RSS. This can be slower than the
original in-memory capture because it prioritizes stable disk-backed
identity and lossless parity; assess measurements before opting into any
real backtest. The following integration milestone must preserve
`min_option_true_ranges`, all execution decisions, costs and final reports
before enabling quote-journal replay inside the H6 simulation runner.


### Phase 1 — bounded time-bucket journal matching (experimental)

The original SQLite-backed `StreamingSignalQuoteJournal` passed the
user's full 14-day quote replay parity A/B benchmark: 457 signal events,
29,703 captured quote records, zero differences across 12 runs. However,
its median runtime was **85.740s vs 15.894s** for the full-frame
capture (5.39× slower) and its process peak RSS was **84,258 KiB vs
83,256 KiB** (1,002 KiB more). **Do not promote this journal to the
normal H6 runner.** Quote matching previously ran an indexed SQLite
interval query once for every quote row with a selected symbol, which
can be disproportionately expensive when ticks repeat inside a time window.

A new opt-in `matching_mode="BUCKET_CACHE"` in
`StreamingSignalQuoteJournal.capture_quotes(...)` caches only the
candidate signal intervals for a short wall-clock bucket. It still
checks the exact `signal_ns < quote_ns <= end_ns` condition for each
quote, supports duplicate and arbitrarily out-of-order CSV rows, and
retains the original source arrival order. The bounded LRU has three
separate controls: `bucket_minutes` (default 5),
`max_cache_buckets` (default 256), and
`max_cached_candidates` (default 4096). If the number of candidates
in one bucket exceeds the candidate budget, it **does not cache the
oversized bucket**, instead matching from a streaming SQLite cursor
with no unbounded candidate list. The original per-quote SQL matcher
is the unchanged default and independent correctness reference.

Run the same full-frame versus journal comparison with the cached
matching *only in the experimental journal*:

```powershell
.\.venv\Scripts\python.exe -m backtest.benchmark_signal_quote_journal `
  --directory backtest/data/delta-history/segments/2026-08-24_09-22 `
  --start 2026-09-01T00:00:00Z `
  --end 2026-09-15T00:00:00Z `
  --output backtest/reports/signal-quote-journal-bucket-ab `
  --chunk-rows 512 --max-session-rows 4096 `
  --journal-matching BUCKET_CACHE `
  --bucket-minutes 5 --max-cache-buckets 256 `
  --max-cached-candidates 4096 --rounds 3
```

The report includes total database lookups, cache hits and misses,
evictions, dense-bucket fallbacks, and peak cache entries/candidates
along with independent-process time/RSS and complete zero-tolerance
quote/event replay comparisons. The baseline remains the unmodified
full-frame positional capture, not the old journal. For the exact
previous journal behavior, omit `--journal-matching` or set
`--journal-matching SQL`.

**Promotion gate:** Historical parity must remain at zero differences
and the measured time/RSS tradeoff must improve materially; only then
consider integrating quote replay into actual trade simulation. Full
trade entries/exits, fees, GST, scenario report parity, option true
ranges and end-to-end bounded process RSS remain pending. The JSON
Strategy Lab and all existing trading defaults are unchanged.
