param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
$PackageRoot = $PSScriptRoot

function Resolve-RepoRoot {
    param([string]$ExplicitRoot)

    if ($ExplicitRoot) {
        $resolved = (Resolve-Path $ExplicitRoot).Path
        if (Test-Path (Join-Path $resolved "backtest\plain_bt123_2026.py")) {
            return $resolved
        }
        throw "RepoRoot does not contain backtest\plain_bt123_2026.py: $resolved"
    }

    $candidates = @()
    $current = $PackageRoot
    for ($i = 0; $i -lt 4; $i++) {
        $current = Split-Path -Parent $current
        if ($current) { $candidates += $current }
    }
    $candidates += (Get-Location).Path

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path (Join-Path $candidate "backtest\plain_bt123_2026.py")) {
            return $candidate
        }
    }

    throw "Could not locate the repository root automatically. Run again with -RepoRoot C:\path\to\Delta-Strategy-Builder"
}

$RepoRoot = Resolve-RepoRoot $RepoRoot
Write-Host "Repository: $RepoRoot" -ForegroundColor Cyan

$Targets = @(
    @{
        Name = "ema_vwap_research.py"
        Source = Join-Path $PackageRoot "integration\ema_vwap_research.py"
        Target = Join-Path $RepoRoot "backtest\ema_vwap_research.py"
        ExpectedOriginalSha256 = "9CC7908EAD99A92FCCA4C1CD11A823EDD67048F80BBB4C8091733119158401E8"
        ExpectedMergedSha256 = "BAC840F0768A118D3488E1D3DA8617B4FC6771DCA0F0F7BD3E7912E277C13A84"
    },
    @{
        Name = "plain_bt123_2026.py"
        Source = Join-Path $PackageRoot "integration\plain_bt123_2026.py"
        Target = Join-Path $RepoRoot "backtest\plain_bt123_2026.py"
        ExpectedOriginalSha256 = "EDA3235E20AB64493BACAA00C7E012CFCD2EAC031A88E7C7382B26667E0976BC"
        ExpectedMergedSha256 = "FDBD74E88E7FFEA6E36DE48887E4C984792ED5B5A3C462AC285F2D37FFBB8400"
    }
)

# Validate every source and every current target before touching anything.
foreach ($item in $Targets) {
    if (-not (Test-Path $item.Source)) {
        throw "Merged source file missing: $($item.Source)"
    }
    if (-not (Test-Path $item.Target)) {
        throw "Backtest file missing: $($item.Target)"
    }

    $sourceHash = (Get-FileHash -Algorithm SHA256 $item.Source).Hash.ToUpperInvariant()
    if ($sourceHash -ne $item.ExpectedMergedSha256) {
        throw "Package integrity check failed for $($item.Source). Expected $($item.ExpectedMergedSha256), got $sourceHash"
    }

    $currentHash = (Get-FileHash -Algorithm SHA256 $item.Target).Hash.ToUpperInvariant()
    if ($currentHash -eq $item.ExpectedMergedSha256) {
        throw "$($item.Name) already appears to contain this merged decision-trace update. Nothing was changed."
    }
    if ($currentHash -ne $item.ExpectedOriginalSha256) {
        throw @"
Safety check stopped the install because your file changed after you uploaded it:
$($item.Target)
Expected current hash: $($item.ExpectedOriginalSha256)
Actual current hash  : $currentHash

Nothing was modified. Upload the newer file before applying this package.
"@
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backups = @()

# Back up BOTH originals before replacing either one.
foreach ($item in $Targets) {
    $backup = "$($item.Target).before-decision-trace-$stamp"
    Copy-Item $item.Target $backup -ErrorAction Stop
    $backupHash = (Get-FileHash -Algorithm SHA256 $backup).Hash.ToUpperInvariant()
    if ($backupHash -ne $item.ExpectedOriginalSha256) {
        throw "Backup verification failed for $backup"
    }
    $backups += @{
        Name = $item.Name
        Target = $item.Target
        Backup = $backup
        OriginalSha256 = $item.ExpectedOriginalSha256
    }
    Write-Host "Backed up: $backup" -ForegroundColor DarkGray
}

try {
    foreach ($item in $Targets) {
        Copy-Item $item.Source $item.Target -Force -ErrorAction Stop
        $installedHash = (Get-FileHash -Algorithm SHA256 $item.Target).Hash.ToUpperInvariant()
        if ($installedHash -ne $item.ExpectedMergedSha256) {
            throw "Installed file verification failed for $($item.Target)"
        }
        Write-Host "Updated: $($item.Target)" -ForegroundColor Green
    }

    # Syntax-check using the project's Python if present.
    $python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $python) {
        & $python -m py_compile `
            (Join-Path $RepoRoot "backtest\ema_vwap_research.py") `
            (Join-Path $RepoRoot "backtest\plain_bt123_2026.py")
        if ($LASTEXITCODE -ne 0) {
            throw "Python compile verification failed."
        }
        Write-Host "Python compile verification passed." -ForegroundColor Green
    }

    $manifest = @{
        installed_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        backups = $backups
    } | ConvertTo-Json -Depth 5
    Set-Content -Path (Join-Path $PackageRoot "last-install.json") -Value $manifest -Encoding UTF8

    Write-Host "" 
    Write-Host "Decision trace installed successfully." -ForegroundColor Cyan
    Write-Host "strategy.py was not modified." -ForegroundColor Cyan
    Write-Host "Run your normal manual_combination backtest to generate decision_events.csv." -ForegroundColor Cyan
}
catch {
    Write-Host "Install failed. Restoring both original files..." -ForegroundColor Yellow
    foreach ($backup in $backups) {
        if (Test-Path $backup.Backup) {
            Copy-Item $backup.Backup $backup.Target -Force
        }
    }
    throw
}
