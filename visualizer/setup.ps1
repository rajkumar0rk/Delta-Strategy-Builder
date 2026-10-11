$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Repo = Split-Path -Parent $Root
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Expected existing project venv at $Python" }
Write-Host "Installing Strategy Lab backend dependencies..." -ForegroundColor Cyan
if (Get-Command uv -ErrorAction SilentlyContinue) { uv pip install --python $Python -r (Join-Path $Root "backend\requirements.txt") } else { & $Python -m ensurepip --upgrade; & $Python -m pip install -r (Join-Path $Root "backend\requirements.txt") }
Write-Host "Installing Strategy Lab frontend dependencies..." -ForegroundColor Cyan
Push-Location (Join-Path $Root "frontend"); try { npm install } finally { Pop-Location }
Write-Host "Setup complete." -ForegroundColor Green
