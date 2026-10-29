# Project orientation

This repository contains a shared `backtest/` research/archive package and the maintained **`visualizer/` BTC Strategy Lab** app. See [the canonical Strategy Lab project contract](../../visualizer/codex/PROJECT.md) and [futures guide](../../visualizer/codex/FUTURES_BACKTEST.md).

The app supports `OPTIONS` (original) and `FUTURES` (`BTCUSD` perpetual) strategy modes; JSON import schema stays **15**. Futures uses completed OHLC candles as research execution proxies, independent LONG/SHORT rules, simulated fees/GST/funding assumptions, and separately labeled estimated margin and drawdown.

Merged development work: futures engine, lifecycle/funding fixes, replay, Delta contract *snapshot*, frozen historical holdout workflow, and internal chart/backtest parity audit. **All remain research-only**; passing CI has not validated profitability against the user's complete local archive.

Source-of-truth code: `visualizer/backend/app/models.py`, `futures_engine.py`, `futures_contract.py`, `futures_validation.py`, `futures_audit.py`, `main.py`, and `visualizer/frontend/src/components/FuturesSettings.tsx`.

Historical data belongs in `backtest/data/delta-history` with `catalog.json`; never duplicate, move or alter the archive for a documentation task.

The older standalone research workflow under `backtest/` is separate and retains its own `AGENTS.md` rules. Read [root AGENTS.md](../../AGENTS.md) and [visualizer/AGENTS.md](../../visualizer/AGENTS.md).
