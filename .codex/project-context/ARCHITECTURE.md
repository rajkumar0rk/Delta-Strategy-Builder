# Architecture orientation

Read the maintained, complete [Strategy Lab architecture](../../visualizer/codex/ARCHITECTURE.md) and [change impact matrix](../../visualizer/codex/CHANGE_IMPACT_MATRIX.md) before coding.

- `visualizer/backend/app/engine.py`: dispatches `market_type=OPTIONS` to the option engine and `FUTURES` to `futures_engine.py`.
- `visualizer/backend/app/futures_engine.py`: OHLC-proxy fills, lifecycle, stops, fees, funding importer, margin *estimates*, result files.
- `visualizer/backend/app/futures_contract.py`: dated public BTCUSD contract snapshot and optional published margin-tier *research* calculations.
- `visualizer/backend/app/research.py`: execution-replay / holdout; `futures_validation.py`: frozen train/holdout/stress job; `futures_audit.py`: internal chart/fill/fee parity checks.
- `visualizer/backend/app/main.py`: job API endpoints; `frontend/src/components/ReplayResearchPanel.tsx`: replay/validation/audit controls.
- `visualizer/backend/app/models.py` and `frontend/src/types.ts`: config schema. `ai_prompt.py`: dynamically generated importable strategy prompt.
- `backtest/data/delta-history/catalog.json`: canonical market-history index; never modify as a side effect.

The internal parity audit **does not** fully reproduce position-aware lifecycle readiness in chart preview and **does not** verify Delta bid/ask fills, historical liquidation, or INR conversion. No trades or profit values are certified by documentation or tests alone.
