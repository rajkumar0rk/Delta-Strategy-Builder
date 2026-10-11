# Unified Delta History Archive

Public-history backtests use one logical archive at:

`backtest/data/delta-history`

The archive stores each date range in `segments/` and records active coverage in
`catalog.json`. Shards avoid one multi-gigabyte CSV and allow future months to be
downloaded or resumed independently.

## Existing data migration

Run once from the repository root:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive migrate
```

## Download a future month

To append every missing completed UTC day through yesterday, rerun:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync --through-yesterday
```

Only download completed dates. After a month has ended, for example:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync --month 2026-11
```

To download a specific inclusive date range:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync `
  --start-date 2026-10-04 `
  --end-date 2026-10-07
```

The command reuses cached raw responses when rerun. Use `--refresh` only when a
cached Delta response must deliberately be replaced.

## Inspect coverage

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive status
```

For manual-combination backtests, configure:

```toml
[backtest]
source = "PUBLIC_HISTORY"
directory = "backtest/data/delta-history"
start_date = "2025-01-01"
end_date = "2026-10-03"
months = []
```
