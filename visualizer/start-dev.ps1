$ErrorActionPreference="Stop"
$Root=$PSScriptRoot;$Repo=Split-Path -Parent $Root;$Python=Join-Path $Repo ".venv\Scripts\python.exe"
if(-not(Test-Path $Python)){throw "Expected $Python"}
$env:STRATEGY_LAB_PROJECT_ROOT=(Resolve-Path $Repo).Path
$cmd="`$env:STRATEGY_LAB_PROJECT_ROOT='$($env:STRATEGY_LAB_PROJECT_ROOT)'; Set-Location '$Root\backend'; & '$Python' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010"
Write-Host "API: http://127.0.0.1:8010" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command",$cmd | Out-Null
Write-Host "UI:  http://127.0.0.1:5174" -ForegroundColor Cyan
Set-Location (Join-Path $Root "frontend"); npm run dev
