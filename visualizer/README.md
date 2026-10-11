# BTC Strategy Lab V15.1

V15.1 adds a **correctness hardening pass** on top of V15 storage/performance hygiene and Codex project context. New runs no longer duplicate large arrays inside `summary.json`; normal ANALYSIS runs compress diagnostic artifacts, optimizer/ablation inner runs use COMPACT persistence, and a Storage Manager can compact legacy result folders, pin important runs, and apply explicit retention cleanup.

The repository now also includes `AGENTS.md`, scoped backend/frontend `AGENTS.md` files, and a `codex/` project-context folder so coding agents have a stable architecture/correctness/command reference before modifying the project.

## V15.1 correctness fixes

V15.1 fixes four audited correctness issues:

1. **Pandas 3 timestamp resolution** — higher-timeframe indicator aggregation no longer assumes datetime integers are nanoseconds; datetime-aware resampling works with ns/us storage.
2. **UTC candle boundaries** — 10m/15m/30m/1h candles use fixed UTC close boundaries, so changing only the requested `From` time cannot regroup overlapping historical candles.
3. **Position sizing safety** — contract `min_quantity` and `size_increment` are always enforced. `risk.enforce_trade_budget_strict` is a UI/config toggle: ON rejects minimum/fixed quantity when premium-notional + entry fee exceeds budget; OFF allows the minimum valid quantity to exceed budget intentionally.
4. **Collision-proof results** — run IDs include milliseconds plus a random suffix and result folders are created exclusively rather than merged with an existing folder.

The results UI also permanently identifies the archive as **LOW_FIDELITY_SYNTHETIC_BBO**: historical option bid/ask and sizes are reconstructed estimates, not recorded L1 execution data, and SELL margin is not modeled.

The app folder is now detected dynamically. The current layout can be `Delta-Strategy-Builder\visualizer` without writing results/cache/strategies into a separate hard-coded `strategy-lab` directory.

## V15/V15.1 result storage

New backtests can use one of three persistence profiles:

- **COMPACT** — compact `summary.json`, exact `strategy.json`, and `trades.csv`; recommended for large research sweeps.
- **ANALYSIS** — COMPACT plus gzip-compressed markers, equity curve and retained decision events; recommended for normal interactive backtests.
- **FULL DEBUG** — diagnostic artifacts stay uncompressed for direct manual inspection.

The API result returned for a just-completed run still contains the current trades/markers/equity needed by the UI. Persistence is what changes. Cache replays reconstruct those arrays from dedicated artifacts, and COMPACT runs reconstruct entry/exit markers from trades.

The Storage Manager reports result size separately from expensive reusable quote SQLite indexes. It can:

- compact V1–V14 result folders in place by gzip-compressing large text diagnostics;
- remove duplicated `trades`/`markers`/`equity_curve`/`series_meta` arrays from legacy `summary.json`;
- remove rebuildable per-run analysis ZIPs;
- pin important runs;
- preview and explicitly delete old **unpinned** runs using a size/age/recent-run retention policy;
- optionally apply that retention policy after successful future backtests.

Automatic cleanup is disabled by default. Quote SQLite indexes are not deleted by result cleanup.

## Codex project context

Start with `AGENTS.md`. More detailed context is in:

```text
codex/PROJECT.md
codex/ARCHITECTURE.md
codex/DATA_AND_BACKTEST_RULES.md
codex/COMMANDS.md
codex/CHANGE_CHECKLIST.md
backend/AGENTS.md
frontend/AGENTS.md
```

These files document the current architecture, no-look-ahead/data correctness rules, storage model, verification commands and safe-change expectations.

## Default market-data root

Strategy Lab now prefers:

```text
C:\projects\workspace\Delta-Strategy-Builder\backtest\data\delta-history
```

Repository-relative form:

```text
backtest/data/delta-history
```

The archive must contain `catalog.json` plus the segment directories referenced by that catalog. V15.1 treats `catalog.json` as the authoritative segment list. Compatibility junctions/folders outside `delta-history` are not recursively rediscovered, so the same physical history is not counted twice.

You can still override the root with:

```powershell
$env:STRATEGY_LAB_DATA_ROOT = "D:\somewhere\delta-history"
```

If the unified archive does not exist yet, V15.1 falls back to the legacy `backtest/data` root for compatibility.


## V15.1 self-healing archive preflight

Strategy Lab can now use the repository archive utility directly when the selected archive range contains uncovered **completed UTC days**. The UI offers both:

- **Check / download missing data** for the selected range;
- **Auto-download missing completed UTC days before backtest** as an opt-in toggle.

The backend calls the existing repository command through the same project Python environment:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync `
  --start-date YYYY-MM-DD `
  --end-date YYYY-MM-DD
```

The downloader remains append-safe: Strategy Lab first plans uncovered catalog intervals, downloads only completed UTC dates, waits for `catalog.json` to be updated by `backtest.history_archive`, reloads the archive, then runs the normal physical-file and candle preflight. If an **existing catalog segment** is present but one of its normalized files is missing, V15.1 reports that as a repair problem rather than silently replacing a potentially multi-month migrated segment.

The download job uses the existing backtest progress/cancellation mechanism. Stopping a download leaves the history utility's cached raw responses reusable on the next attempt.

## Multiple entry sessions

`session.windows` is now the canonical entry-session schedule. A new entry is allowed when the completed candle falls inside **any** configured window in `session.timezone`.

Example:

```json
{
  "timezone": "Asia/Kolkata",
  "windows": [
    {"start": "01:00", "end": "06:00"},
    {"start": "10:00", "end": "21:00"}
  ],
  "blocked_weekdays": []
}
```

That allows entries from `01:00–06:00` and `10:00–21:00`, while blocking the gap between the windows. Windows may also cross midnight, for example `22:00–02:00`. Existing V1–V15.1 strategy files with only `session.start`/`session.end` are automatically migrated into a one-item `session.windows` list.

## Unified archive mode

The UI defaults to **Unified archive (recommended)**. For a requested From/To interval, V15.1:

1. reads `catalog.json`;
2. selects only catalog segments whose `[start, end_exclusive)` interval overlaps the request;
3. checks that the catalog itself has no uncovered gap in the requested range;
4. checks physical `underlying_bars.csv`, `option_instruments.csv`, and `option_quotes.csv` files for every selected segment;
5. merges and de-duplicates overlapping rows;
6. builds/reuses quote indexes only for the selected segments.

The `/api/archive` endpoint reports the current root, catalog source/fidelity, update timestamp, declared coverage, segments, file presence and catalog gaps.

## Big Trend Outcome Discovery

V15.1 includes the research panel under the Big Trend Detector. It is intentionally separate from live strategy rules.

Choose:

- forward window in strategy candles;
- minimum future move percentage that qualifies as a **BIG** move;
- Big Trend Score threshold used to sample **FAKE** strong-looking setups;
- number of prelude candles used for feature snapshots;
- event separation so one long move is not counted on every candle.

The analyzer then:

- labels historical CALL/PUT BIG moves from future price action;
- samples high-score / strong-phase setups that fail to reach the BIG threshold as FAKE trends;
- snapshots only information available at the label candle or earlier;
- compares configured indicator/state features between BIG and FAKE samples;
- ranks features by standardized separation;
- shows Big Trend Score calibration buckets and historical hit rates;
- shows recent labeled events and their forward MFE/opposite move.

**Important:** future candles are used only to assign historical research labels. They are never inserted into the strategy frame and cannot affect backtest entries. Indicator, score, phase and breakout/retest snapshots keep the normal completed-candle/no-look-ahead semantics.

This is useful for questions such as:

```text
Before real BTC big moves, was ADX materially higher than before fake trends?
Did ATR expansion matter?
Was EMA separation / ATR larger?
Did Big Trend Score 80-90 actually outperform score 70-80?
Were BIG moves usually already in CONFIRMATION or BIG_TREND phase?
```

The output is descriptive research, not a profitability guarantee.

## Existing Big Trend engine retained

V15.1 keeps the V12 directional state machine and rule operands, including:

```text
COMPRESSION
IGNITION
CONFIRMATION
BIG_TREND
EXHAUSTION

call_big_trend_score / put_big_trend_score
*_big_trend_score_persistence_count
*_breakout_level
*_bars_since_breakout
*_retest_ready
*_false_breakout
*_trend_too_old
```

ADX/DMI, formulas, count-based rules, multi-bar slope, candle strength, ATR expansion, overextension and higher-timeframe indicators remain available in the visual builder.

## Start on Windows PowerShell

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

UI:

```text
http://127.0.0.1:5174
```

API docs:

```text
http://127.0.0.1:8010/docs
```

## Archive maintenance

The history archive itself is managed outside Strategy Lab. With your repository history utility you can keep it current using:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync --through-yesterday
```

and inspect coverage with:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive status
```

Strategy Lab reads that archive. For compatibility with V15, generated results/cache/saved strategies keep using the existing repository `strategy-lab` storage location unless you override the corresponding `STRATEGY_LAB_*_ROOT` environment variables.

## Verification

Backend tests:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q
```

Frontend production build when dependencies are installed:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\frontend
npm run build
```
