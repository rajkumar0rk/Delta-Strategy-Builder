# Decision Trace Merge for Current Delta-Strategy-Builder Files

This package was generated specifically from the two files uploaded on 2026-10-06.

It preserves the newer `plain_bt123_2026.py` functionality, including R2 recording-manifest support, October segment coverage, dynamic segment/month selection, execution-attempt aggregation, configurable execution parameters, and data-fidelity fields.

It adds timestamped decision tracing only. `strategy.py` is never modified.

## Safety

`install.ps1` checks the exact SHA-256 hashes of both current backtest files before doing anything. It then creates and verifies backups of **both** files before replacing either one. If replacement or Python compilation fails, it restores both backups automatically.

Expected current hashes:

- `ema_vwap_research.py`: `9CC7908EAD99A92FCCA4C1CD11A823EDD67048F80BBB4C8091733119158401E8`
- `plain_bt123_2026.py`: `EDA3235E20AB64493BACAA00C7E012CFCD2EAC031A88E7C7382B26667E0976BC`

## Install

From this package folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -RepoRoot C:\projects\workspace\Delta-Strategy-Builder
```

After installation, run your normal backtest, for example:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder
.\.venv\Scripts\python.exe -m backtest.manual_combination --output 40_visualizer_decision_trace
```

The run can now create `decision_events.csv` in the combined report and segment report directories.

## Restore

To restore the exact backups created by the most recent successful install:

```powershell
powershell -ExecutionPolicy Bypass -File .\restore-last-install.ps1
```

The patch files are included for review.
