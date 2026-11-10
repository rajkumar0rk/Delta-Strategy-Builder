# BTCUSD 1H Bearish Continuation with 5M Point Trailing

Research-only, opt-in Futures execution. Introduced on the feature branch
`feat/futures-1h-candle-pattern-5m-trailing-20261110`.

## Importable example

`visualizer/backend/examples/btc-futures-1h-bearish-4th-candle-5m-200-point-trail.strategy.json`

Set `market_type=FUTURES`, `timeframe=5m`, `direction_mode=PUT`,
`futures.candle_pattern.enabled=true`, `position_policy=EXCLUSIVE`.
Ordinary entry rule trees are not required; candle-pattern detection is
performed by the dedicated completed-hour scanner. Ordinary PUT exit rule
conditions must be empty: the dedicated 5M fixed/profit-stop manager controls
exits; optional max-hold or forced-clock exits remain separate explicit risk
settings. When the UI enables the mode, it clears old PUT exits, time-stop
and session-end exit overrides, selects short-only 5m, and blocks weekends.

## Exact strategy semantics

- The source is twelve **consecutive, complete** UTC-aligned 5m bars per 1H candle.
  If the hour lacks any five-minute source candle, that hour cannot confirm
  a setup; the three-hour consecutive setup history is reset. No 1h bar is
  actionable while still forming.
- `entry_candle=4`: 1H C1 green (`close>open`); C2 red (`close<open`)
  AND C2 close strictly below C1 low; C3 red. SHORT at C4 OPEN
  (immediately following C3 close, also the next 5m bar open). Set
  `entry_candle=3` to use C1 and C2 and enter at C3 OPEN.
- `doji_filter_enabled=true` rejects a setup unless **each** setup
  candle has `abs(close-open)/ (high-low) * 100 >= doji_threshold_percent`.
  Zero-range candles are ineligible when the filter is enabled.
- Freeze the initial fixed stop at entry:
  `PATTERN_HIGHEST_HIGH` = the maximum HIGH across C1/C2/C3
  (or C1/C2 for third-candle mode);
  `SETUP_CANDLE_HIGH` = C3 HIGH (or C2 HIGH).
  Add `stop_buffer_ticks * futures.tick_size`. Reject nonprotective stops;
  never trail or change the *initial* frozen level itself.
- The **active** protective stop is tested against every following 5M candle
  HIGH, including the entry candle. For SHORT, touching or exceeding it exits.
  If the candle opens beyond the stop, fill at the worse opening proxy. The
  user-selected adverse execution costs, fees, and GST still apply.
- `take_profit_mode=TRAILING_POINTS`: using a SHORT fill at 100000,
  `activation_points=200`, `pullback_points=200`, activate only when an
  **eligible completed** 5M close is at/below 99800. The active protective
  stop becomes at most 99800 from the **next** 5M candle.
  A further eligible close of 99700 leaves it at 99800. An eligible close
  of 99500 ratchets it to 99700 (next candle only).
  The stop never increases for SHORT. `trailing_ignore_doji=true` ignores
  doji closes for both activation and ratchet, but does not suspend stop-hit
  monitoring. The initial stop snapshot remains available for auditing.
- `take_profit_mode=FIXED_POINTS` uses `fixed_target_points` from the
  actual executed entry; `NONE` uses the frozen protective stop without a
  price target or trailing profit.
- The same 5M bar can touch both a stop and fixed take-profit. The existing
  OHLC engine treats the adverse stop as first. The candle cannot prove the
  intrabar sequence. An active stop can be touched *before* an eligible close
  would otherwise activate the trailing mechanism.
- Session windows and `blocked_weekdays` apply at the next-open **entry**.
  Set `session.timezone=Asia/Kolkata` and `blocked_weekdays=[5,6]` for
  Monday-Friday entries. The 1H data anchor remains UTC, independent of
  the IST session timezone.

## Config and incompatibilities

All fields belong to `futures.candle_pattern`:
`enabled`, `entry_candle` (3 or 4), `doji_filter_enabled`,
`doji_threshold_percent` (0..100), `stop_anchor`, `stop_buffer_ticks`,
`take_profit_mode`, `activation_points`, `pullback_points`,
`fixed_target_points`, `trailing_ignore_doji`, `size_mode`,
`equity_risk_percent`, `max_lots`, and
`max_estimated_risk_multiple`.

Set `futures.stop_loss_percent=null`,
`futures.take_profit_percent=null`; disable
`futures.rule_risk`, `futures.pullback`, `futures.adaptive`,
and Options `pattern_trade`. Never silently mix execution planners.
Legacy strategies default to `candle_pattern.enabled=false`.

Whole-lot sizing reuses Futures estimated equity-risk,
margin guards, assumed adverse fills, fees/GST, and daily loss budget.
`RISK_EQUITY` is **not** a guaranteed actual exchange loss cap.

## Performance, fidelity, and regression

The scanner traverses the five-minute history once, holds at most three
confirmed hourly candles and a single 12-bar aggregation bucket, and stores
only matched setup events. The entry state remains bounded to one
pending order and one active position. No network request or repeated
full-frame resampling is made inside the trading loop.

This remains `RESEARCH_ONLY`: no tick sequence, historical futures L1
bid/ask, order book, exchange liquidation, or validated funding is fabricated.
Funded backtests still require the supplied observed settlement CSV;
`EXCLUDE_WITH_WARNING` explicitly omits funding.

Regression tests: `visualizer/backend/tests/test_futures_candle_pattern.py`.
Run the complete backend pytest suite, frontend tests and build, and verify
unchanged existing rule-risk, options, adaptive, pullback, and funding cases
before merging. Futures engine cache identity changes from 15 to 16.


## Chart-only 1H view (no change to trading behavior)

The BTC Strategy Lab chart now defaults to `1H (chart only)` when
`futures.candle_pattern.enabled=true`, with a user-selectable
`5M (execution)` alternative. This selector is React presentation state:
**do not edit** `StrategyConfig.timeframe` (it stays `5m`), backend
simulation, risk rules, trade timestamps, or saved JSON.

The UI groups existing 5m-close OHLCV observations into UTC hour-open
chart candles. A historical hour is shown only when all twelve consecutive
5m closes are present. The final range-end hour may be displayed as a
**partial** hour and is labeled as such, never as a completed 1h signal.
Hourly display indicators and condition scores sample the last available 5m
value in that bucket; this is a visualization of the known values, not
permission to use that end-of-hour snapshot before the close.

Entry/exit/study/alert markers map onto the containing UTC 1h display
candle, with their original timestamp retained for tooltips. When a marker
belongs to an omitted incomplete historical hour, it remains in the
unmodified 5m payload and appears in the 5m view instead. Changing the
selector does not recalculate backtest trades or P&L.

Implementation:
`frontend/src/components/hourlyChartDisplay.ts` and
`TradingChart.tsx`; focused tests:
`frontend/src/components/hourlyChartDisplay.test.ts`.
