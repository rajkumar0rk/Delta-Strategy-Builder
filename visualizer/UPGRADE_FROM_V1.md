# Upgrade from V1 / V1.1

1. Stop the old visualizer terminals.
2. Back up or rename the existing `visualizer` directory.
3. Copy the V2 `visualizer` directory to the repository root.
4. Run setup again:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

5. Start V2:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

Existing backtest reports work immediately. To get timestamped early ZigZag /
Momentum rejection events in newly generated reports, optionally run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-decision-trace.ps1
```

The decision-trace installer is guarded by hashes and creates backups. It never
modifies `strategy.py`.
