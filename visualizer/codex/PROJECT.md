# Project context

## Product

**BTC Strategy Lab V15.1** is a local-first visual strategy research and options backtesting application. It is not a live broker/order-routing system.

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
