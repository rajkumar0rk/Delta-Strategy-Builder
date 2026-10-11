$ErrorActionPreference = "Stop"
$manifestPath = Join-Path $PSScriptRoot "last-install.json"
if (-not (Test-Path $manifestPath)) {
    throw "No last-install.json was found in this update folder."
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
foreach ($item in $manifest.backups) {
    if (-not (Test-Path $item.Backup)) {
        throw "Backup file is missing: $($item.Backup)"
    }
}
foreach ($item in $manifest.backups) {
    Copy-Item $item.Backup $item.Target -Force
    Write-Host "Restored: $($item.Target)" -ForegroundColor Green
}
Write-Host "Restore complete." -ForegroundColor Cyan
