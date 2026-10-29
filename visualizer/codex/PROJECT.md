# Project context

## Product

**BTC Strategy Lab** is a local-first visual strategy research and options/BTCUSD perpetual futures backtesting application. It is not a live broker/order-routing system.

Repository layout (relevant subset):

```text
Delta-Strategy-Builder/
├── .venv/
├── backtest/
│   ├── history_archive.py
│   ├── providers/delta_india.py
│   └── data/delta-history/
│       ├── catalog.json
│       └── segments/...
└── visualizer/  # current app folder; may also be named strategy-lab/
    ├── backend/
    ├── frontend/
    ├── examples/
    ├── strategies/       # user-created; may not exist in source package
    ├── results/          # generated; may be very large in legacy installs
    ├── .cache/           # quote indexes + backtest cache
    ├── codex/
    └── AGENTS.md
```

## Current engine capabilities

- 5m/10m/15m/30m/1h strategy candles built from downloaded 5m underlying history.
- EMA/SMA/VWAP/RSI/ATR/MACD/Stochastic/Stoch RSI/Bollinger/volume/Donchian.
- ADX/+DI/-DI, derived formulas, candle strength, ATR expansion, overextension.
- Confirmed pivots, market structure/BOS, regular + hidden divergence, support/resistance.
- DAY_LEVELS: previous-day range/confirmed swing extremes, first older outside swings, frozen daily snapshots, near/touch flags and an alert-only preset. See DAY_LEVEL_ALERTS.md.
- Count-based history rules, crosses-within-window, multi-bar slope.
- CALL-only, PUT-only, or BOTH; BUY or SELL option positions.
- Multiple independent entry lifecycles per direction.
- Multiple entry-session windows per local day.
- Continuous/persistent Big Trend Score and directional trend phase state machine.
- Remembered breakout, retest, false-breakout block/rearm, trend age.
- Shared and directional NO-TRADE rules.
- Daily risk controls and fee-aware minimum-edge filter.
- Delta options fee cap + GST model.
- Unified history archive with catalog-based segment selection and opt-in missing-day download.
- Parameter sweep, ablation, walk-forward/robustness research, historical Big-vs-fake trend discovery.
- Cooperative progress/cancellation.
- V15 compact result storage and retention controls.
- V15.1 Pandas-resolution-safe HTF indicators and fixed UTC HTF candle boundaries.
- V15.1 configurable strict trade-budget enforcement with mandatory exchange quantity validity.
- V15.1 collision-proof result IDs.

## User workflow assumptions

The user commonly tests long BTC history ranges and many parameter combinations. Performance, deterministic behavior, and avoiding unnecessary reprocessing are important. The user wants visual configurability rather than features that exist only in code.

## V15.2 + V16 phase 1

Backtest request warm-up and strict REQUIRE handling, mark-to-market risk sampling, stale-quote unresolved position metadata, ablation fixes, and analysis-only execution cost sensitivity. The strategy import schema remains version 15. No live broker routing or recorded order-book replay. See V16_EXECUTION_STRESS.md and FUTURES_BACKTEST.md.


## Separate BTCUSD perpetual futures research (v1)
The opt-in `market_type=FUTURES` routes the same indicator, completed-5m data, signal trees and alerts into `backend/app/futures_engine.py`. LONG uses CALL signal rules, SHORT uses PUT rules, with exclusive positions, estimated OHLC/open execution and dedicated futures contracts/fees, leverage, price-based stops, funding CSV, session and daily risk. It is research only, not historical exchange-accurate margin/liquidation or an actual bid/ask replay. `market_type=OPTIONS` preserves the original options engine. See `FUTURES_BACKTEST.md`.

### Futures correctness hardening (merged)
Accepted futures orders consume independent lifecycle limits; pre-range candles warm lifecycle state without trades. Funding settlement occurs only for positions remaining open at candle close. Estimated intrabar stop-versus-margin ordering is conservative but not a proven exchange execution path. Futures fills support configurable tick rounding and additional adverse tick slippage; no historical futures BBO is available. The simulator remains RESEARCH_ONLY. Futures execution replay uses dedicated futures slippage/fee/funding assumptions; historical holdout and internal chart parity jobs are implemented. Complete position-aware chart lifecycle parity, true broker fills, mark prices and liquidation remain unverified.

## Six completed futures implementation milestones
1. Separate BTCUSD futures LONG/SHORT backtester.
2. Lifecycle, funding and conservative fills.
3. Futures replay, equity proxy and rejection diagnostics.
4. Dated Delta contract snapshot, historical funding guard and optional current-published margin tiers.
5. Frozen-strategy train/holdout/stress validation (`futures_validation.py`).
6. Internal rule/fill/fee/chart-marker parity audit (`futures_audit.py`).

Merged code is still **RESEARCH_ONLY**. Real historical P&L requires running on an accessible archive. Importable strategies retain schema_version **15**, while backtest request settings are separate. See `FUTURES_BACKTEST.md` and `FUTURES_STRATEGY_JSON_PROMPT.md`.
