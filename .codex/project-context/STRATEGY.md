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
