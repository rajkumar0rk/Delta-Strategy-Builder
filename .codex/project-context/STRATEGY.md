# Current Strategy Model

The maintained matrix uses completed BTC 5-minute candles and buys a selected
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
