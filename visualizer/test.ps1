$ErrorActionPreference="Stop";$Root=$PSScriptRoot;$Repo=Split-Path -Parent $Root;$Python=Join-Path $Repo ".venv\Scripts\python.exe"
Push-Location (Join-Path $Root 'backend');try{& $Python -m pytest -q}finally{Pop-Location}
Push-Location (Join-Path $Root 'frontend');try{npm run build}finally{Pop-Location}
