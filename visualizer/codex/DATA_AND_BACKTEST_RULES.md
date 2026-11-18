# Data and backtest correctness rules

## Unified archive

Default root: `../backtest/data/delta-history`.

`catalog.json` is authoritative. Select only catalog segments whose half-open interval `[start, end_exclusive)` overlaps the requested range. Physical files expected per segment:

```text
underlying_bars.csv
option_instruments.csv
option_quotes.csv
```

Missing completed public-history dates may be downloaded only through `python -m backtest.history_archive sync ...`. Existing catalog segments with missing normalized files should be reported rather than silently replaced.

## Candle semantics

Normalized underlying timestamps are candle-close timestamps. Higher-timeframe candles must be constructed only from complete contiguous 5m source candles. Missing rows mean the higher-timeframe candle is discarded, never synthesized.

Higher-timeframe candles are anchored to fixed UTC clock-close boundaries and MUST NOT depend on the requested From time. For example 00:05 + 00:10 form the 10m candle ending 00:10. Higher-timeframe strategy operands become available only after the complete higher-timeframe candle closes.

Do not convert datetimes to integers and assume nanoseconds. Pandas 3 can use microsecond-resolution datetime storage; use datetime-aware resampling/rounding.

## Pivot/divergence semantics

Confirmed swing pivots are actionable only after their right-side confirmation bars have completed. Divergence may compare oscillator values at historical pivot bars, but the divergence signal is emitted only at confirmation time.

## Option execution

- Long BUY entry: ask + configured slippage.
- Long BUY exit: bid - configured slippage.
- Short SELL entry: bid - configured slippage.
- Short SELL exit: ask + configured slippage.
- Never substitute option candle close when a modeled executable quote is required by the engine.

Delta option fee model per side:

```text
notional fee = spot * quantity * contract_value * 0.01%
premium cap  = option premium * quantity * contract_value * 3.5%
base fee     = min(notional fee, premium cap)
GST          = base fee * 18%
total fee    = base fee + GST
```

Personal income tax is not part of per-trade backtest P&L.

## Research future labels

Trend discovery can inspect future candles only to label whether a historical setup became a BIG or FAKE move. Any feature used to explain/predict the event must come from the label candle or earlier.

## Position sizing

`min_quantity` and `size_increment` from the selected option contract are mandatory exchange-validity constraints. Invalid FIXED quantities are rejected.

`risk.enforce_trade_budget_strict` is user-configurable:

- `true`: reject a valid minimum/fixed quantity when premium-notional + entry fee exceeds `budget_usd`;
- `false`: BUDGET mode may step up to the minimum valid quantity even above `budget_usd`.

This toggle does not disable cash checks and does not model SELL margin/collateral.

## Data fidelity

The public archive is `LOW_FIDELITY_SYNTHETIC_BBO`: option bid/ask is reconstructed from 1m option candle closes using an estimated spread, and sizes are synthetic. P&L/fills are research estimates, not proof of historical executability. SELL margin/collateral/liquidation is not modeled.


## Replay cutoff, stop tails, and chart paging (2026-11-18)

- Requested intervals are half-open UTC: `[start,end)`. Entry quotes and
  indicator/underlying-triggered exit quotes **at or after** `end` are excluded.
- A completed source 5m monitoring candle that closes before `end` may trigger
  `UNDERLYING_SIGNAL_CANDLE`, even after the last completed larger
  strategy-timeframe candle. Trigger times are candle closes, not inferred wick
  timestamps. Triggering from a candle that began before actual option entry is
  disallowed for ambiguous WICK stops.
- Option premium stops/profit protection remain active on valid observed quotes
  through the replay cutoff, including quotes after the last complete strategy
  candle. Underlying stop signals and premium exits are resolved chronologically.
- `END_OF_DATA` can close only at a strictly post-entry quote less than
  `execution.max_exit_quote_delay_seconds` before the requested cutoff.
  Without a fresh quote, the position remains unresolved, and closed-trade
  P&L / profit factor exclude it. This avoids stale close prices, not lost P&L.
- The optional user-provided SELL margin estimate is enforced even if general
  `enforce_cash=false`, whenever `require_sell_margin_estimate=true`. It is not
  a Delta account-risk-engine estimate.
- Chart preview supports `chart_offset_bars` and a maximum of 30,000 **contiguous
  unmodified** candles per page. Paging never changes the strategy backtest
  range, but historical preview indicator warm-up remains a finite approximation.
- Synthetic historical bid/ask, real quote sequencing below 5m, exchange
  collateral/liquidation, and true L1 queue fills remain **unavailable** unless
  independently collected from an appropriate source. They must not be
  represented as solved by deterministic code fixes.
