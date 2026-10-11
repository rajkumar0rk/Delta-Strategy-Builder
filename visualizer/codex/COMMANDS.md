# Common commands

Run from Windows PowerShell unless noted.

## Start Strategy Lab

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

UI: `http://127.0.0.1:5174`

API docs: `http://127.0.0.1:8010/docs`

## Backend tests

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q
```

## Frontend build

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\frontend
npm run build
```

## Frontend regression tests

Run from `visualizer/frontend`:

```powershell
npm run build
npm run test
```

Vitest runs frontend unit and server-rendered component tests without a browser.
Coverage includes strategy defaults (CALL/PUT separation, budget and fee settings)
and V16 execution-stress report rendering (baseline/stress rows, exclusions,
and missing values). This is **not** a replacement for the browser workflow
and chart hover/timeframe smoke tests.

## History archive

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder
.\.venv\Scripts\python.exe -m backtest.history_archive status
.\.venv\Scripts\python.exe -m backtest.history_archive sync --through-yesterday
```

Specific inclusive UTC date range:

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive sync `
  --start-date 2026-10-04 `
  --end-date 2026-10-07
```

## V15.1 storage

Use the Storage Manager in the UI to compact legacy result folders before deleting runs. Pin important runs before applying retention cleanup.
