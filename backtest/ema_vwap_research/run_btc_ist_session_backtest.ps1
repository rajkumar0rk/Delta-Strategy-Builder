$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
Set-Location $ProjectRoot

$Development = "data/delta-2026-09-15_22"
$Holdout = "data/delta-holdout-2026-07-25_08-24"
$Output = "backtest/ema_vwap_research/reports/ist-session-timing-v1"

uv run python backtest/ema_vwap_research/btc_options_ist_session_backtest.py `
  --development $Development `
  --holdout $Holdout `
  --output $Output `
  --policy all
