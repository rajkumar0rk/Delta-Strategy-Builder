# Visualizer — issues fixed (2026-11-18)

**Status:** Implemented and CI-verified on branch `fix/visualizer-backtest-logic-20261118`. Pending review/merge in [PR #90](https://github.com/rajkumar0rk/Delta-Strategy-Builder/pull/90). These changes are **not** on `master` yet.

## Fixed issues

| Issue | Fix |
|---|---|
| Wrong option strike selected when front expiry lacks the intended strike | Select the intended ATM/ITM/OTM strike across eligible expiries before considering alternative strikes. |
| Backtest results vary near the requested start due to cold indicators | Use earlier causal history for strategy and chart indicator warm-up, then trim signals/trades to the requested interval. |
| Invalid bid/ask quotes can become fills | Reject zero/negative bids and crossed quotes, using valid records only within the allowed quote-delay window. |
| Quote executes after the replay end or after contract expiry | Reject out-of-window entry quotes and expired-contract entry fills; constrain condition/time/ATR exit quote lookup to replay end. |
| Stop-loss can assume pre-entry candle wicks happened after entry | Skip ambiguous partial-candle WICK stops; continue to use completed monitoring candles and subsequent option-side quotes. |
| Artificial same-quote exit at end of data | Do not use the entry quote as an end-of-data exit. Report unresolved exposure instead of fabricating a trade. |
| Closed-trade drawdown hides interim losses | Add quote-observed mark-to-market drawdown separately from realized/closed-trade drawdown. |
| SELL entries can ignore a needed capital estimate | Add an optional user-entered per-contract USD margin estimate and enforce the available-cash guard. |
| Unintended four-hour exits in new strategies | New strategies default to `max_hold_minutes=null`; explicitly configured older values remain unchanged. |
| Backtest controls stay busy while the chart loads | Finish job handling independently from the chart preview, loading it asynchronously. |
| Old trade markers can appear after editing the strategy | Clear or retain markers based on the associated completed-run configuration. |
| Saved strategy load fails from an incorrect `.resolve()` call | Resolve the entire strategy-folder path, not the string literal. |
| Long-running server accumulates cached frames and finished jobs | Cap bars/instruments RAM caches and retained completed-job payloads. |
| Missing tests for these regressions | Add regression tests and a dedicated Actions workflow covering backend and frontend build. |
| Missing/undefined profit factor displayed as zero | Display an unavailable value rather than a misleading numeric zero. |

## Validation

- Dedicated visualizer backtest correctness workflow: **passed**
- Existing RSI/VWAP signal-candle stop verification workflow: **passed**
- Python backend correctness and legacy regression suites: **passed**
- Frontend tests, TypeScript compilation and production build: **passed**

## Known limits / not fixed

- Historical option quotes are reconstructed/synthetic, so fills cannot prove live execution quality.
- Exchange-specific SELL margin, collateral, and liquidation requirements are not verified by the user-entered estimate.
- OHLC monitoring cannot reconstruct the exact tick when a candle wick touched a stop.
- The chart's 30,000-bar preview guard remains; complete multiyear chart paging was not implemented.
- The corrected engine has not been re-run to establish revised full-history strategy profitability.

**Re-test note:** Execution semantics and indicator warm-up changed. Re-run important strategies on the new branch and compare trade-level results rather than carrying forward old profit factors.
