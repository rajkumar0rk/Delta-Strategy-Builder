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

Normalized underlying timestamps are candle-close timestamps. Higher-timeframe candles must be constructed only from complete contiguous source candles on **fixed UTC clock-close boundaries**. For example, a 10m candle ending 00:10 is built from the 5m closes at 00:05 and 00:10. Changing the requested backtest start must never re-phase later candles. Missing rows mean the higher-timeframe candle is discarded, never synthesized.

Higher-timeframe indicator aggregation must use timezone-aware datetime operations, not assumptions about the integer unit returned by Pandas datetime casts. Pandas may store timestamps at nanosecond or microsecond resolution.

Higher-timeframe strategy operands become available only after the complete higher-timeframe candle closes.

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

## Quantity and result persistence correctness

- FIXED quantity must satisfy the selected contract's `min_quantity` and `size_increment`; otherwise reject the entry rather than simulate an impossible order.
- BUDGET mode may exceed the configured budget only when `allow_minimum_quantity_over_budget=true`; this is an explicit user choice for exchange minimum quantities.
- Result directories must be uniquely allocated with `exist_ok=False`; concurrent/same-second runs must never share or overwrite artifacts.
