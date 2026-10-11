# Common commands

Run from Windows PowerShell unless noted.

## Start Strategy Lab

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\strategy-lab
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

UI: `http://127.0.0.1:5174`

API docs: `http://127.0.0.1:8010/docs`

## Backend tests

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\strategy-lab\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q
```

## Frontend build

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\strategy-lab\frontend
npm run build
```

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

## V15 storage

Use the Storage Manager in the UI to compact legacy result folders before deleting runs. Pin important runs before applying retention cleanup.
