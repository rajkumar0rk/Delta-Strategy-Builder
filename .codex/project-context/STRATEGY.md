# Legacy manual options strategy matrix (not the whole Strategy Lab)

The separate legacy manual-options matrix uses completed BTC 5-minute candles and buys a selected
ATM CALL or PUT option after a valid entry signal.

Baseline directional entry conditions are:

- CALL: close above VWAP, EMA9 > EMA20 > EMA50, RSI in the bullish band.
- PUT: close below VWAP, EMA9 < EMA20 < EMA50, RSI in the bearish band.

The manual configuration can replace the baseline entry with a ZigZag-style
pullback or momentum-breakout mode and can layer filters such as MACD, H6,
fee-aware movement, M30 direction, volume ratio, DTE, sessions, and weekdays.

BT1, BT2, and BT3 share the base entry structure but use different exit
families. Exit behavior is also affected by `exit_policy`, `exit.ema_rule`,
early-failure settings, maximum hold, expiry exit, and profit protection.

The current checked-in config runs BT1 with `entry.mode = "BASELINE"`, a plain
exit, `FAST_OR_MID_VS_SLOW`, no maximum hold, no profit protection, no optional
entry filters, public history, and September 2026 dates.

Saved Strategy Lab JSON files are research inputs. Do not assume their rule
schema has exact parity with the Python runner; add an importer and parity tests
before claiming an exact backtest.

## Distinguish Strategy Lab futures
This file describes the standalone `backtest/` options matrix, **not** the maintained `visualizer/` default strategy or BTCUSD futures engine. For an importable Strategy Lab JSON see `visualizer/examples/btcusd-futures-research.template.json`; for generation instructions see `visualizer/codex/FUTURES_STRATEGY_JSON_PROMPT.md`. Futures research P&L is not proven executable or profitable.

## November 2026 configurable intraday futures stop order

The opt-in 1H EMA50/200 + 15M EMA20 pullback **stop-market** strategy lives in `visualizer/backend/examples/btc-futures-intraday-1h-15m-stop-market.strategy.json`. Its authoritative generation guidance is `visualizer/codex/FUTURES_STRATEGY_JSON_PROMPT.md` and `visualizer/codex/STRATEGY_JSON_GENERATION_PROMPT.md`. Default legacy futures pullbacks remain close-confirm/next-open. The intraday order mode adds bounded pending stop entry, signal-candle ATR SL, fixed 2R, optional 1H crossover exclusion, remaining daily equity risk, separate force-exit clock, assumed half-spread and partial research-only parity. Re-run tests and benchmark relevant 5M history; these are not historical Delta execution fills or a profitability guarantee.

## November 2026 Options market extension

The canonical option-side cross-market implementation guide is `visualizer/codex/OPTIONS_PULLBACK_BACKTEST.md` with importable `visualizer/backend/examples/btc-options-intraday-pullback.strategy.json`. Shared neutral helpers live in `visualizer/backend/app/shared_execution.py`. Only opt-in BUY CALL/PUT option strategies use the new pending underlying ATR stop and BTC 2R price targets. Option premium execution and fees remain quote-backed in `engine.py`; no assumption that BTC 2R equals option premium 2R, and no fabricated option fills. The original Options/Futures modes are backward compatible; verify via backend/frontend regression and representative local archival backtest.
