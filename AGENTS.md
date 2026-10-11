# Delta Strategy Backtest Agent Guide

## Scope

Work on the backtest engine and research assets in this repository. Do not turn
this workspace into an execution or mobile application repository.

Preserve these directories unless the user explicitly asks otherwise:

- `backtest/data`
- `backtest/reports`
- `visualizer`
- `strategy-lab`
- `strategy-lab-user-data`

## Source Of Truth

- Main runner: `backtest/manual_combination.py`
- Main config: `backtest/config.manual-combination.toml`
- Strategy calculations: `backtest/ema_vwap_research.py`
- Shared math: `backtest/calculations.py`
- Public archive: `backtest/data/delta-history/catalog.json`
- Data maintenance: `backtest/history_archive.py`
- R2 import: `backtest/recorded.py`
- Tests: `tests/`

Read `.codex/project-context/README.md` before substantial work.

## Working Rules

1. Make one research change at a time and preserve its exact configuration.
2. Do not optimize only for win rate or total P&L.
3. Report fees, trade count, profit factor, drawdown, average win/loss, largest
   win, P&L per trade, profitable months, CALL/PUT split, and outlier-free P&L.
4. Label public option execution as low fidelity. Do not treat synthetic sizes
   or reconstructed spreads as observed market depth.
5. Use only completed candles for signals and avoid lookahead.
6. Never overwrite an existing scenario result folder.
7. Keep credentials out of source, reports, and chat output.

## Verification

Run before finishing engine changes:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

For configuration or runner changes, also execute a short representative
scenario when practical and inspect its `summary.json` and `trades.csv`.
