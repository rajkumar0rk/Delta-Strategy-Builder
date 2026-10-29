# BTC Strategy Lab architecture (maintained source)

For full module ownership and change impact read [codex/ARCHITECTURE.md](codex/ARCHITECTURE.md) and [codex/CHANGE_IMPACT_MATRIX.md](codex/CHANGE_IMPACT_MATRIX.md).

The maintained source is `visualizer/`. React/Vite (`frontend/`) calls FastAPI (`backend/app/main.py`). `engine.py` routes `market_type=OPTIONS` through the options research backtester or `market_type=FUTURES` through `futures_engine.py`. The latter uses underlying OHLC proxies rather than exchange-executable historical order-book prices. Pydantic schema: `backend/app/models.py`. Data: repository-owned `backtest/data/delta-history/catalog.json`.

Research modules: `backend/app/research.py` (replay/holdout), `futures_validation.py` (frozen-strategy holdout and stress), `futures_audit.py` (limited internal chart/backtest parity), `futures_contract.py` (dated published BTCUSD snapshot, research tier calculations). `backend/app/ai_prompt.py` builds importable strategy JSON instructions. `frontend/src/components/ReplayResearchPanel.tsx` exposes historical validation and internal parity actions.

The entire app is **research-only**; no live broker order placement or guaranteed exchange fills. Chart overlays do not certify exact position-aware lifecycle parity; historic mark prices, actual liquidation and INR portfolio accounting remain unavailable.

## Historical legacy visualizer integration (retained context)

The original decision-trace visualization below describes an earlier integration and **is not the current app's sole architecture**.

### Legacy boundary

The visualizer is a read-only analytics application. Trading/research decisions
remain in the existing Python backtest engine. `strategy.py` is not imported by
the web application and is not modified by the V2 decision-trace integration.

## Backend

FastAPI exposes run discovery, overview, chart data, trades, equity, decision
events, selected-trade investigation, and performance diagnostics.

Large option history is loaded **per selected symbol** and cached by file mtime +
symbol. BTC bars and report JSON/CSV reads are also mtime-keyed and cached.

Selected-trade analysis computes:

- option BID/ASK series;
- executable BID-based MFE/MAE;
- signal-time EMA/VWAP/RSI/ATR/volume diagnostics;
- DTE and spread checks;
- matching execution attempt.

## Frontend

React + TypeScript uses Lightweight Charts v5. A single chart object contains:

1. BTC candles + indicators;
2. BTC volume;
3. selected option BID/ASK when a trade is selected.

This gives the BTC and option series one synchronized time scale.

Replay filters every visible data class to the current replay timestamp so
future information is not displayed.

## Optional decision tracing

`integration/ema_vwap_research.py` adds observation-only trace collection to the
existing ZigZag, Momentum, signal, and execution pipeline. The decision trace is
an output artifact; it does not change the result of the boolean decision rules.

`integration/plain_bt123_2026.py` writes combined `decision_events.csv` and stores
only a count in the top-level summary to avoid unnecessarily bloating
`summary.json`.
