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
