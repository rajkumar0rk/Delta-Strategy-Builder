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
- The current Strategy Lab field is `risk.enforce_trade_budget_strict` (default true). When true, reject over-budget valid quantities; when false, BUDGET mode may step up to the contract's valid minimum above budget. **Exchange min_quantity and size_increment are still mandatory.** `allow_minimum_quantity_over_budget` is **not** a StrategyConfig field.
- Result directories must be uniquely allocated with `exist_ok=False`; concurrent/same-second runs must never share or overwrite artifacts.

## Current Strategy Lab source of truth
For live schema fields and futures details read `visualizer/codex/DATA_AND_BACKTEST_RULES.md`, `visualizer/codex/FUTURES_BACKTEST.md` and `visualizer/backend/app/models.py`. The current FUTURES backtester is `RESEARCH_ONLY` with user-controlled assumptions, not verified historical exchange fills or margins. Do not treat this root-level handoff document as a current API schema.
