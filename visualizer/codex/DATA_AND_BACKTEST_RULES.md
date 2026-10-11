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

## Multi-timeframe warm-up and chart/backtest parity

- Indicator calculations for both chart preview and backtest must include a conservative historical warm-up window **before** the requested range. Do not display warm-up bars or allow warm-up trades.
- Automatically include earlier *catalogued* archive segments as underlying-only warm-up inputs in ARCHIVE/AUTO modes, without expanding the tradable option universe. Explicit SINGLE/MULTI selection remains scoped.
- Flag insufficient **contiguous** warm-up history. No padding or generated candles; incomplete warm-up means early values may depend on dataset start. Backtest requests that support `warmup_policy=REQUIRE` must reject missing history.
- Higher-timeframe OHLC and indicators use actual distinct on-grid base candle close timestamps. Duplicates, missing closes, or off-grid times must not form a complete candle.
- Compare overlapping chart-preview and backtest indicator values at the same timestamp; no access to a higher-timeframe candle before its close.
- A change to these semantics invalidates previous cached backtests. Keep historical results unchanged and identify the behavior change in reports.
