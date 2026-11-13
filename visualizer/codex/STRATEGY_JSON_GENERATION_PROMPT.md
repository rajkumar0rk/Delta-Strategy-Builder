# Strategy JSON generation: verified options contract (November 2026)

> Source of truth: `visualizer/backend/app/models.py::StrategyConfig` and `visualizer/backend/app/ai_prompt.py::build_strategy_prompt`. This repository branch implements **BTC options research**, not a standalone BTC futures trading engine. The backtest requires option instruments and observed/reconstructed option quotes. Never copy fields from a different, newer version's prompt without confirming the live Pydantic schema. Generated JSON uses `{"schema_version":15,"app":"BTC Strategy Lab","strategy":{...}}`; only the nested `strategy` is passed to `StrategyConfig`.

## RSI(14) + session VWAP picture

Use a 5m strategy, two non-chart-only indicator instances (`RSI` period 14 and `VWAP` session reset), `direction_mode=BOTH`, `call_action=BUY`, `put_action=BUY`, and `position_policy=EXCLUSIVE`. These underlying signals buy CALL for bullish exposure and buy PUT for bearish exposure; **do not** confuse SELL CALL with a short BTC futures position.

- CALL entry group ALL: `rsi14 GT 60`, `close GT vwap`.
- PUT entry group ALL: `rsi14 LT 40`, `close LT vwap`.
- Suggested, not image-specified, CALL exit group ANY: `rsi14 CROSSES_BELOW 60`, `close CROSSES_BELOW vwap`.
- Suggested, not image-specified, PUT exit group ANY: `rsi14 CROSSES_ABOVE 40`, `close CROSSES_ABOVE vwap`.
- Use one enabled lifecycle per direction; set extra EMA/volume filters, profit targets and premium stops to NONE when matching the picture. Choose reset timezone and time in the VWAP indicator. A threshold comparison permits signals on every candle above/below; use `CROSSES_ABOVE/CROSSES_BELOW` only when a crossing is explicitly required.

## Configurable underlying entry signal-candle stop

`risk.stop_loss` is backwards compatible. Select `mode=UNDERLYING_SIGNAL_CANDLE` to freeze the **completed entry signal candle** low for bullish BTC exposure (BUY CALL / SELL PUT) and high for bearish BTC exposure (BUY PUT / SELL CALL). `signal_candle_buffer_points` (default 0) widens the stop in BTC points. This is not an option-premium stop and it is not recalculated or trailed after entry.

`signal_candle_trigger` is `WICK` (default, completed bar low/high touches stop) or `CLOSE` (bar closes through stop). `signal_candle_execution_timeframe` is `strategy` (default) or `5m`, letting higher-strategy-timeframe signals use already completed 5m BTC monitoring candles. Detection is at the **monitoring candle close**, not at the unknowable tick time within its wick. Stop detection never uses pre-entry bars.

The actual trade is an **option**. When BTC stop triggers, exit at the first **subsequently observed** valid option quote, using BID less slippage for BUY positions or ASK plus slippage for SELL positions, and apply Delta fees + GST. If no subsequent quote exists, log unresolved stop exposure instead of fabricating an option fill. A later quote may cause a materially worse loss than the BTC stop level suggests. The underlying stop is directional for both BUY and SELL options. An earlier premium-based exit can precede a later underlying stop. No historical L1 queue, tick sequencing, live stop-market guarantee, or verified short-option margin.

## Model limitations and verification

- Backtest strategy times: 5m, 10m, 15m, 30m, 1h. Higher indicators: strategy, 5m, 10m, 15m, 30m, 1h; exact multiple only. The uploaded external prompt mentioning 4h, 1D, futures rule_risk, and option pullback is **not** a contract for this GitHub revision.
- Backtests use reconstructed LOW_FIDELITY_SYNTHETIC_BBO in the public archive; never describe observed quotes as historical executable fills.
- Cache version must change whenever exit semantics change. Preserve old strategy defaults and analyze trade markers, missing quotes, end-of-data, slippage, fees, and no-lookahead behavior.
- To generate the full authoritative prompt, invoke the backend AI prompt endpoint; it appends the current full `StrategyConfig.model_json_schema()`, not a hand-maintained schema copy.
- Verify with `python -m pytest -q` under `visualizer/backend` and `npm run build` under `visualizer/frontend`. Do not claim successful verification unless actually executed.
