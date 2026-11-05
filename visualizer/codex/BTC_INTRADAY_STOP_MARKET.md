# Configurable BTC perpetual 1H EMA trend + 15M EMA20 pullback stop-market research

This is an **opt-in**, backwards-compatible extension of the existing futures planner. Import `visualizer/backend/examples/btc-futures-intraday-1h-15m-stop-market.strategy.json`, schema v15. Do not edit legacy OPTIONS / futures defaults, and never claim exchange-executable fills.

## Exact model

- Completed 1H EMA50 > EMA200 and 1H close > EMA50 for LONG; reverse for SHORT. Exclude crosses in the previous three completed 1H bars; reject pending entry when this filter invalidates.
- Completed 15M confirmation: LONG low <= EMA20 and bullish close > EMA20; SHORT high >= EMA20 and bearish close < EMA20.
- At setup close, freeze signal candle high/low and ATR14, place stop-market order one tick beyond high/low, valid for the next six 5M candles only (two 15M candles). A high/low touch triggers; breakout close not required.
- Initial SL = signal low - 0.1 ATR (LONG), signal high + 0.1 ATR (SHORT), directionally tick-rounded away from entry. TP = 2R using actual adverse entry fill and frozen SL. Neither stop nor TP moves.
- One active position and one pending order; entry window 14:00–21:59 IST (22:00 exclusive) and separate daily mandatory 23:45 IST open-of-bar exit. Disable max-hold, rule-based exits and premature session-end closing.
- Risk is the smaller of 0.5% current cash/equity and remaining 1% of starting-day equity after net realized losses. Calculate size down to whole lot using stop risk, both taker fees and GST, assumed adverse spread/slippage and margin checks. Insufficient minimum size skips entry. Stop gaps can exceed intended maximum loss.

## Implementation contract

`futures.pullback.execution_mode`: `CLOSE_CONFIRM_NEXT_OPEN` (legacy, default) or `STOP_MARKET_INTRABAR` (opt-in). `stop_anchor`: `SWING` (legacy) or `SIGNAL_CANDLE`. Other adjustable fields: `breakout_buffer_ticks`, `breakout_buffer_points`, `max_wait_bars`, `stop_buffer_atr`, `reward_r_multiple`, `require_volume`, `equity_risk_percent`, `size_mode`, `max_lots`, `max_estimated_risk_multiple`, `trend_fast_ema_id`, `trend_slow_ema_id`, `trend_close_indicator_id`, `trend_crossover_block_bars`, `cancel_on_trend_invalidation`, `futures.force_exit_time`, `futures.extra_half_spread_bps`, `session.windows`, and `risk.max_daily_loss_percent`.

Re-use `app/models.py`, `futures_setups.py`, `futures_engine.py`, `futures_audit.py`, `ai_prompt.py`, `frontend/src/types.ts`, `FuturesSettings.tsx` and existing jobs/replay/validation. All default behavior is preserved. The loop is linear in data length with one-time full-history aggregation, bounded swing/crossover state and a single pending order. Do not resample or scan all history per bar; size search is logarithmic in lots. JSON/schema version remains 15; futures cache identity is bumped.

## Research limitations and checks

5M OHLC can verify a wick touch but not true intrabar sequence. When entry and stop/target fall within the same 5M candle, assume unfavorable stop-first ordering; gap-through-trigger fills at the worse open. An assumed extra half-spread is a scenario parameter, not observed BBO. Independent preview audit checks stop triggers and fill proxies but returns `PARTIAL_RESEARCH_ONLY`; it does not independently reconstruct all 15M setup snapshots or any exchange tick path.

Required checks: test invalid strategy references/clock syntax; completed HTF warmup/no lookahead; two-15M expiration; gap fills; one pending order; trend invalidation and last-three-hour cross; stop/target ambiguity; daily reset and remaining-risk cap; force-exit cutoff; costs/funding warnings; backwards-compatible OPTIONS and legacy Futures; per-run cache invalidation, performance regression and frontend build. Use historical data and unchanged out-of-sample periods before making P&L claims.
