# Delta Strategy Backtest

Research and backtesting workspace for BTC options and BTCUSD perpetual futures
research using Delta Exchange India historical data.

This repository contains the Python calculation engine, historical-data
archive, experiment configurations, reports, tests, visualizer, and Strategy
Lab. It is not an order-execution service.

## Quick Start

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backtest.manual_combination
```

The manual runner reads
`backtest/config.manual-combination.toml` and writes a versioned scenario
folder under `backtest/reports/manual-combinations/`. Existing results are not
overwritten.

## Main Areas

- `backtest/`: current research engine, data tools, configurations, and reports.
- `backtest/data/delta-history/`: unified sharded public-history archive.
- `tests/`: regression tests for the current engine.
- `visualizer/`: **maintained BTC Strategy Lab source** (React + Python backend), Codex docs, examples, futures research and parity/holdout APIs.
- `strategy-lab/`: legacy/runtime Strategy Lab results, cache and saved-strategy storage in some installations; **not the source directory**.
- `strategy-lab-user-data/`: local Strategy Lab user workspace.
- `.codex/project-context/`: concise handoff material for future Codex chats.

## Data Fidelity

- BTC signals use completed native 5-minute candles where available.
- Public-history option execution uses one-minute option candles and a
  synthetic spread. Treat those results as low fidelity.
- Imported R2 recordings can supply observed bid/ask snapshots, but coverage is
  limited to recorded sessions and may contain gaps.
- Never describe a result as live executable unless its quote source and fill
  assumptions justify that claim.

## Research Discipline

Evaluate more than win rate. Every comparison should include net P&L after
fees, profit factor, maximum drawdown, average win and loss, largest win, P&L
per trade, profitable months, CALL/PUT split, trade count, and outlier-free
results. Change one variable at a time and retain the exact configuration with
the output.

The six BTCUSD futures *implementation* milestones are merged, but the futures engine
uses **research-only OHLC execution estimates**, not verified exchange bid/ask,
INR wallet liquidation or demonstrated historical profitability. See
[visualizer/codex/FUTURES_BACKTEST.md](visualizer/codex/FUTURES_BACKTEST.md),
[visualizer/examples](visualizer/examples), and
[visualizer/codex/FUTURES_STRATEGY_JSON_PROMPT.md](visualizer/codex/FUTURES_STRATEGY_JSON_PROMPT.md).

See [backtest/README.md](backtest/README.md) and
[.codex/project-context/README.md](.codex/project-context/README.md).
