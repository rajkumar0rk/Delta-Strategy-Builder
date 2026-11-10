# Copy-paste prompt — BTCUSD Futures Strategy Lab JSON

## Optional fixed-point BTCUSD Futures take-profit (November 2026)

The existing opt-in generic `futures.rule_risk` execution supports three **mutually exclusive** target modes:
- `reward_r_multiple=2` and `take_profit_points=null`: legacy R-multiple target (default, unchanged).
- `reward_r_multiple=null` and `take_profit_points=200`: absolute 200 BTCUSD underlying price-point target from the **executed fill**, LONG entry + 200 or SHORT entry - 200, rounded conservatively toward entry to the configured tick size. This is **not** $200 net P&L and is not a leveraged ROI percentage.
- Both fields `null`: no fixed target (protective stop and any enabled trailing stop remain active).

These parameters are configurable in the Futures rule-risk settings UI and validated by `FuturesRuleRiskConfig`. Do not enable simultaneous R and point targets; do not set point distance below `futures.tick_size`. Both legacy `futures.stop_loss_percent` and `futures.take_profit_percent` must remain `null` in `rule_risk` mode, with `futures.pullback.enabled=false` and `futures.adaptive.enabled=false`. This reuses the existing stop-first intrabar, conservative gap-fill, per-lot fee/GST and margin accounting; fixed-point target calculation is O(1) per fill and creates no new history scans.

Example updated: `visualizer/backend/examples/btc-futures-4h-donchian-atr-trend.strategy.json` (4h EMA200, 1h Donchian55/ADX25, 2 ATR stop, 3 ATR trailing, 0.5% equity risk, fixed +200/-200 point take-profit). Tests: `visualizer/backend/tests/test_futures_point_targets.py`. OHLC path ambiguity, fees, funding, gaps, margin and historical quote limits remain; live fill/pricing fidelity is not claimed.


## Fixed BTCUSD price-point take profit for rule-risk Futures (November 2026)

- `futures.rule_risk.take_profit_points` is an optional **underlying BTCUSD price distance**, measured from the **simulated executed entry price**, not USD account profit, ticks, percent, leveraged return, or ATR/R multiple. For a 200-point target, LONG exits at entry + 200, SHORT exits at entry − 200, conservatively rounded toward entry to a valid `futures.tick_size`. The fill simulator still applies its exit slippage/fees, so realized P&L is not guaranteed to equal exactly 200 points.
- Set `futures.rule_risk.enabled=true`, `take_profit_points=200`, `reward_r_multiple=null`, `futures.stop_loss_percent=null`, `futures.take_profit_percent=null`. The two `rule_risk` target modes are mutually exclusive and validated; `take_profit_points=null` preserves the old default `reward_r_multiple=2`, and **both null** means no fixed take-profit.
- No change to 4h completed-only EMA filtering, Donchian/ADX entry rules, `stop_mode=ATR`, `atr_stop_anchor=ENTRY_FILL`, ATR initial stop or dynamic trailing, fee-aware equity sizing, AMRS, VWAP, pullback, options, or existing futures percent exits. Stops win ambiguous same-candle stop-and-target tests; gaps and settlement/mark/liquidation remain research approximations.
- Updated example: `visualizer/backend/examples/btc-futures-4h-donchian-atr-trend.strategy.json`. Verification: `visualizer/backend/tests/test_futures_points_target.py`.


## PR #69 — 4H closed-candle filters and generic ATR trailing Futures (November 2026)

- This implementation builds on the **merged** VWAP + `futures.rule_risk` mode from PR #68. It does **not** add a competing `futures.trend_risk` mode. Existing `futures.pullback`, `futures.adaptive` (AMRS), fixed-percent Futures, VWAP and OPTIONS strategies remain opt-in/backward-compatible.
- The supported strategy and indicator timeframes now include `4h`, aggregated from **48 contiguous 5m candles ending on UTC-aligned 4h boundaries**. For a 1h base strategy, a 4h EMA200 updates only after its 4h candle completes; never use the currently forming HTF candle.
- For 1h Donchian55 + 4h EMA200 + 1h ADX14 trend strategies, set `futures.rule_risk.enabled=true`, `stop_mode=ATR`, `atr_indicator_id` to a **non-chart-only strategy-timeframe ATR** (e.g. `atr14_1h`), `stop_atr_multiple=2`, `stop_buffer_atr=0`, `atr_stop_anchor=ENTRY_FILL`, `trailing_enabled=true`, `trailing_atr_multiple=3`, `trailing_source=HIGH_LOW`, `reward_r_multiple=null`, `size_mode=RISK_EQUITY`, `equity_risk_percent=0.5`, `max_lots` and `max_estimated_risk_multiple`. Disable legacy price stops/target by setting both `futures.stop_loss_percent` and `futures.take_profit_percent` to null. `futures.pullback.enabled` and `futures.adaptive.enabled` must be false.
- `atr_stop_anchor=SIGNAL_CLOSE` and numeric `reward_r_multiple=2` are preserved as backward-compatible defaults for existing PR #68 rule-risk JSON. `ENTRY_FILL` instead uses the **already completed signal candle ATR** to set the protective stop relative to the simulated next-open entry fill; there is no future ATR leak. Whole-lot risk sizing reuses fees/GST, adverse exit slippage, budget, daily loss limit and assumed margin guards.
- Trailing starts from the entry, tracks the highest high/lowest low (or close), **never loosens**, and updates only after the current candle's stop checks; the new stop is executable from the following candle. A gap through the active stop fills conservatively. A `null` R target disables fixed take-profit without disabling the protective stop. This is research OHLC execution; no broker-accurate order book, margin/liquidation or historical funding is implied.
- Importable example: `visualizer/backend/examples/btc-futures-4h-donchian-atr-trend.strategy.json`. Regression checks: `visualizer/backend/tests/test_futures_4h_rule_trailing.py`. Update both the in-app generator `backend/app/ai_prompt.py` and these Codex references whenever schema/logic changes. Reject unrecognized JSON keys before considering a configuration implemented.



## Opt-in VWAP/EMA rule-tree risk (November 2026)

The indicator catalog supports `VWAP` with four **validated** parameters:
`reset_mode="LEGACY_IST_CLOSE_DATE"` (backward-compatible original calculation)
or `"CUSTOM_SESSION_OPEN"`, `timezone` (IANA name, e.g. `Etc/UTC`),
`reset_time` (HH:MM local session-open) and `price_source="hlc3"|"close"`.
Custom reset bins use the completed candle's OPEN time; existing VWAP settings
with no parameters remain unchanged. This is not an arbitrary anchored/event VWAP.

For ordinary FUTURES CALL/LONG and PUT/SHORT rule-tree signals, opt into
`strategy.futures.rule_risk.enabled=true` to use frozen structure stops,
fee-aware R sizing and price-based R-multiple targets, independently of pullback
or adaptive planners. Set `futures.pullback.enabled=false`,
`futures.adaptive.enabled=false`, `futures.stop_loss_percent=null` and
`futures.take_profit_percent=null`; `pattern_trade` must remain disabled.
`rule_risk` fields are `stop_mode="SWING"|"SIGNAL_CANDLE"|"ATR"`,
`swing_lookback_bars`, `atr_indicator_id`, `stop_atr_multiple`,
`stop_buffer_atr`, `reward_r_multiple`, `size_mode="RISK_EQUITY"|"FIXED"`,
`equity_risk_percent`, `max_lots`, and `max_estimated_risk_multiple`.
Provide a non-chart-only `ATR` indicator with the referenced ID when ATR
stops or ATR buffers are active. Choose source timeframe equal to the strategy
timeframe for a same-timeframe stop. The signal-bar snapshot is frozen after
close and its entry executes NEXT bar OPEN; size is rounded DOWN to full lots,
using adverse assumed exit slippage and taker fees/GST. A gap may exceed the
risk budget. Conservative intrabar stop-first logic and approximate margin
accounting are inherited from the Futures engine. Regular EMA/VWAP exits
remain separate rule-tree NEXT-OPEN exits.

Reference importable schema-v15 strategy:
`visualizer/backend/examples/btc-futures-vwap-ema11-rule-risk.strategy.json`.
It implements 5m VWAP + EMA11, a fresh VWAP price crossover with both close
filters, optional rule-based EMA/VWAP exits, a three-candle swing stop, 2R
target, 0.5% equity-risk research sizing and no funding inclusion. These are
*example assumptions*, not independently verified details of the X video.
Do not generate win-rate or P&L claims without a completed backtest.


For **both** OPTIONS and FUTURES strategy generation, start at [STRATEGY_JSON_GENERATION_PROMPT.md](STRATEGY_JSON_GENERATION_PROMPT.md). This file is the futures-specific companion, not the in-app prompt implementation.

You are generating **ONE importable BTC Strategy Lab strategy JSON file** for the maintained `visualizer/` app in `rajkumar0rk/Delta-Strategy-Builder`.

**Read the code before generating:** `visualizer/backend/app/models.py` (`StrategyConfig`, `FuturesConfig`, `FuturesPullbackConfig`, `RuleGroup`, `EntryBehavior`), `visualizer/backend/app/ai_prompt.py`, `visualizer/codex/FUTURES_BACKTEST.md`, and `visualizer/examples/btcusd-futures-research.template.json`. Use actual indicator IDs/operands from `visualizer/backend/app/indicators.py`.

Task: Return **JSON only**, with exactly this outer structure: `{"schema_version":15,"app":"BTC Strategy Lab","strategy":{...}}`. Include the complete valid `StrategyConfig`, not pseudocode, and preserve all fields required by the current source.

## Futures-only semantics
- `strategy.market_type` = `"FUTURES"`. `direction_mode` can be `CALL` for LONG, `PUT` for SHORT, or `BOTH`. CALL entry/exit rules are LONG signals; PUT entry/exit rules are SHORT signals.
- `position_policy` = `"EXCLUSIVE"`: at most one futures position. Signals use **completed** candles; entries and condition exits use the next candle OPEN proxy, not same-candle closes.
- Specify `futures.symbol="BTCUSD"`, `contract_btc=0.001`, `quantity_lots`, `leverage`, `margin_mode`, `maintenance_margin_percent`, `margin_tier_mode` (`FLAT_RESEARCH` default or `DELTA_PUBLISHED_SNAPSHOT` research assumption), `taker_fee_percent`, `gst_percent`, `slippage_bps`, `tick_size`, `slippage_ticks`, `funding_rate_multiplier`, `stop_loss_percent`, `take_profit_percent`, `funding_mode`.
- **Two mutually exclusive risk modes:** legacy mode uses `futures.stop_loss_percent` and `futures.take_profit_percent` as underlying-entry-price percentages (not option-premium percentages or leveraged ROI). Opt-in stateful mode (`futures.pullback.enabled=true`) uses frozen swing-based stop and an R-multiple target instead: set BOTH legacy percent fields to `null`. Contract/margin numbers are a dated public *snapshot*, not historical risk validation.
- **Stateful futures pullback:** strategy timeframe MUST be `5m`; `futures.pullback.setup_timeframe` is `15m`, `30m` or `1h`. Specify non-chart-only setup timeframe EMA and ATR indicators and a 5m VOLUME_SMA indicator, with IDs exactly matching `futures.pullback.ema_indicator_id`, `atr_indicator_id`, `volume_indicator_id`. An HTF candle confirms an EMA touch and directional close (color optional). The engine freezes that candle's high/low breakout level and the last `swing_lookback_bars` completed HTF candle extrema with configurable ATR stop buffer. A SUBSEQUENT completed 5m candle must break the frozen level within `max_wait_bars`, optionally satisfying `require_volume` and `volume_multiplier`. The entry is simulated at the next 5m OPEN. Do NOT invent frozen-level indicators or conditions; the engine handles those internally.
- **Configurable fields:** `futures.pullback` includes `enabled`, `setup_timeframe`, `ema_indicator_id`, `atr_indicator_id`, `volume_indicator_id`, `require_touch`, `require_confirmation_color`, `require_volume`, `volume_multiplier`, `max_wait_bars`, `swing_lookback_bars`, `stop_buffer_atr`, `breakout_buffer_points`, `reward_r_multiple`, `size_mode` (`RISK_EQUITY` or `FIXED`), `equity_risk_percent`, `max_lots`, and `max_estimated_risk_multiple`. Follow the current Pydantic bounds in `FuturesPullbackConfig`. For the illustrative 1h trend strategy retain its 1h filters in the ordinary CALL/LONG and PUT/SHORT entry trees; other strategies may configure different valid completed-candle directional filters. Stateful PULLBACK_SETUP entry selection uses the dedicated planner rather than normal EntryBehavior lifecycle readiness, while ordinary directional rule trees and Big Trend Score still gate eligibility. Ensure max_wait_bars * 5 <= 2 * setup_timeframe_minutes in addition to its own Pydantic bounds. Preserve preserve NO TRADE, session, conflict policy, Big Trend Score, position policy and daily risk limits.
- **Sizing and risk:** in stateful mode, `RISK_EQUITY` sizes downward to whole contract lots from estimated stop loss and round-trip taker fees/GST, bounded by equity risk %, max lots, estimated margin and position limits; `FIXED` respects a configurable estimated-risk allowance. The target is `reward_r_multiple` of entry-to-stop distance with conservative tick rounding. Minimum tradable lots that breach risk/margin are rejected. Never advertise the configured risk % as a guarantee: slippage, stop gaps, funding and exchange liquidation can exceed modeled loss. Existing options `pattern_trade` mode must stay disabled.
- **Reference strategy:** `visualizer/backend/examples/btc-futures-stateful-1h-15m-5m.strategy.json`. Reuse it for the 1h EMA50/200 + ADX14, 15m EMA20 pullback, 5m volume breakout, dynamic stop, 2R target and 0.5% risk seed; do not claim profitability without backtesting.
- Funding: `REQUIRE_CSV` means actual `futures_funding.csv` must be present (`timestamp,symbol,funding_rate`, UTC offsets, fraction). `EXCLUDE_WITH_WARNING` explicitly excludes funding and must be labeled incomplete. Never invent funding rates or treat the pre-2025-09-08 minute-by-minute regime as an 8-hour schedule.
- Do **not** enable `call_breakout_retest.require_retest_for_entry` or `put_breakout_retest.require_retest_for_entry`. Option-specific premium controls remain compatibility fields, **not** futures execution controls. Do not add `train_fraction`, `embargo_bars`, `warmup_candles`, `storage_mode`, replay scenarios or job-specific settings under `strategy`; those belong to separate API requests.
- Use the current indicator catalog and verify every operand output, lifecycle condition, and score/alert reference. Pydantic may ignore unknown fields: reject them separately against the recursive schema. Only use available indicators, confirmed pivots, valid operators and finite numeric inputs. Avoid lookahead or using historical future labels in decisions. Favor fewer high-conviction trades over forced daily entries; avoid guaranteed profit language.

## Validation checklist
1. Confirm JSON parses, outer `schema_version` is **15**, and `StrategyConfig.model_validate(payload["strategy"])` accepts it.
2. Both CALL/PUT lifecycle IDs and indicator references must exist. Do not include dangling condition references or unsupported indicator properties.
3. Risk starting balance, funding assumptions, fee/GST model and max hold are explicit. A successful syntax validation does not prove historical strategy profitability.
4. The current code's `FUTURES` backtest, replay, frozen holdout and internal parity are **RESEARCH_ONLY**; historical Delta executable BBO, mark-price liquidation, INR collateral conversion and actual portfolio tier history are unavailable.
5. Return the **full strategy JSON only**; no explanatory text outside it.

If asked for a suggested research seed, use the repository's futures example as the starting point, preserve its valid schema, and describe performance as **unverified**. Do not fabricate backtest results.

## Intraday 1H/15M stop-market breakout (opt-in, November 2026)

For the exact mechanical 1H EMA50/EMA200 trend + 15M EMA20 rejection strategy, use the validated sample `visualizer/backend/examples/btc-futures-intraday-1h-15m-stop-market.strategy.json` (schema 15). Do NOT generate an approximation using the legacy completed-5m-close breakout.

- Set `futures.pullback.execution_mode="STOP_MARKET_INTRABAR"`, `setup_timeframe="15m"`, `stop_anchor="SIGNAL_CANDLE"`, `require_touch=true`, `require_confirmation_color=true`, `require_volume=false`, `stop_buffer_atr=0.1`, `breakout_buffer_ticks=1`, `max_wait_bars=6`, `reward_r_multiple=2`. The 5m strategy timeframe is the execution data granularity, not the signal timeframe; 6 next 5m bars represent two next 15m candles.
- Attach 1h non-chart-only EMA50, EMA200 and EMA(1) close proxy with `trend_fast_ema_id`, `trend_slow_ema_id`, `trend_close_indicator_id`. Set `trend_crossover_block_bars=3` and `cancel_on_trend_invalidation=true`. The 1h filter is sampled only from confirmed hourly closes. LONG: fast>slow and close>fast; SHORT: fast<slow and close<fast.
- Set `size_mode="RISK_EQUITY"`, `equity_risk_percent=0.5`, `risk.max_daily_loss_percent=1`, `risk.max_hold_minutes=null`, and `futures.stop_loss_percent=null`, `take_profit_percent=null`; stop loss is signal low/high +/- ATR buffer and target is 2R from the executed entry. Risk sizing includes round-trip assumed taker fees/GST and adverse stop execution; it is bounded by remaining estimated daily risk.
- Set entry `session.timezone="Asia/Kolkata"`, one window `14:00–21:59` (5m granularity approximates end-exclusive 22:00), and `futures.force_exit_time="23:45"` for a separate compulsory daily bar-OPEN exit. `extra_half_spread_bps` is a configurable *assumed* cost, not observed futures BBO.
- Exactly ONE pending entry is armed after a completed setup bar. A later base bar high/low crossing the tick-rounded stop level fills with adverse slippage and gap-through-open logic, without requiring a breakout candle close. Orders cancel after `max_wait_bars`, trend invalidation, entry-session close, force-exit time or daily risk gate. No same-candle lookahead: OHLC ambiguity is resolved conservatively (possible pre-entry stop contact is counted as stop); report research-only fidelity.
- Existing `CLOSE_CONFIRM_NEXT_OPEN` pullback mode remains default and unchanged unless the strategy opts into the new execution mode. Never insert stop-market settings into OPTIONS. No preset proves strategy profitability.

Scalability contract: full-history bar/indicator aggregation is done once; pending order count is bounded to one; setup history and hourly crossover tracking use bounded state; runtime per processed candle is amortized constant apart from finite rule evaluation/position sizing. No per-candle full-frame rescan or external network call. Keep the UI, backend Pydantic schema, in-app AI prompt, example JSON, parity warnings and tests synchronized.

## Adaptive 1h-regime Futures execution (AMRS, November 2026)

Use `futures.adaptive.enabled=true` **instead of** `futures.pullback.enabled` when the user requests a regime-switching BTC Futures strategy. Import `visualizer/backend/examples/btc-futures-adaptive-regimes-v1.strategy.json`; its 1h EMA/ADX/ATR_PERCENTILE classifier routes 15m Donchian volume breakouts or completed 15m compression retests to a single bounded 5m stop-market pending order. `futures.adaptive.trend` and `compression` each configure ATR stop and R target. `futures.adaptive.trailing` updates ATR trailing stops based only on the preceding completed 5m bar, activation after favorable R threshold. Risk uses the shared conservative Futures execution/risk engine. Validate against full Pydantic schema, do not create invented keys, and never claim profitable or exchange-verified fills. All strategy JSON schemas stay version 15.


## 1H bearish continuation / 5M fixed-stop & point trail (opt-in)

The exact supported mode is documented in
[`BTC_1H_CANDLE_PATTERN_5M_TRAILING.md`](BTC_1H_CANDLE_PATTERN_5M_TRAILING.md).
For an importable strategy, use:
`visualizer/backend/examples/btc-futures-1h-bearish-4th-candle-5m-200-point-trail.strategy.json`.

- `market_type=FUTURES`, `timeframe=5m`, `direction_mode=PUT` (SHORT),
  `futures.candle_pattern.enabled=true`; disable legacy percentage stop/target,
  rule_risk, pullback, adaptive and OPTIONS pattern execution.
- `entry_candle=4`: completed UTC 1H C1 GREEN; C2 RED closing strictly
  below C1 LOW; C3 RED; enter SHORT at C4 OPEN. `entry_candle=3`
  enters at C3 OPEN after C1/C2. Only twelve complete consecutive
  5m bars may form an hourly candle; missing data invalidates setup.
- `doji_filter_enabled=true` and `doji_threshold_percent=10`
  require setup candle body to be >= 10% of total candle range.
- `stop_anchor=PATTERN_HIGHEST_HIGH` freezes highest 1H HIGH among
  setup candles; `SETUP_CANDLE_HIGH` selects last setup candle HIGH.
  `stop_buffer_ticks=0` is default. Every 5M HIGH checks the active stop.
- `take_profit_mode=TRAILING_POINTS`, `activation_points=200`,
  `pullback_points=200`, `trailing_ignore_doji=true`: activate only
  after eligible completed 5M CLOSE <= actual short entry - 200.
  At activation, protect at least the 200-point level; later eligible
  completed CLOSE updates the stop downward to no higher than
  `close + pullback_points`. New values take effect on the next 5M bar.
  Alternatives: `FIXED_POINTS` with `fixed_target_points` and `NONE`.
- Reuse `size_mode` (FIXED/RISK_EQUITY), `equity_risk_percent`,
  `max_lots`, `max_estimated_risk_multiple`, all existing fees/GST,
  funding, margin guards and risk controls. Block Saturday/Sunday
  with `session.blocked_weekdays=[5,6]`, `timezone=Asia/Kolkata`.
- Clear ordinary PUT exit rule conditions to prevent competing exit behavior; optional risk max-hold and force-exit controls remain separate.\n- Never translate this to legacy `TRAILING_PERCENT`, option premium
  protection, generic ATR trailing, or an unvalidated pseudo-field.
  Keep schema_version=15. Use only supported inputs and mark historical
  OHLC execution as RESEARCH_ONLY.

The scanner runs once in O(N) over completed 5m history and keeps only a
bounded hour aggregate and 3-pattern state. Regression coverage:
`backend/tests/test_futures_candle_pattern.py`.

## Configurable fixed stop from actual entry (C3 / 500 / 1000 / 100)

A SHORT pattern may now use `futures.candle_pattern.stop_anchor="ENTRY_POINTS"`
and `stop_loss_points=500`. The price is frozen **only after** the next-open
SHORT execution fill, as `stop_price=entry_fill+500`; this is distinct from
`PATTERN_HIGHEST_HIGH` and `SETUP_CANDLE_HIGH`. No pattern-derived
placeholder stop is used for risk sizing or entry checks. The engine
conservatively rounds the protective stop to the nearest valid adverse tick.
`stop_buffer_ticks` applies to the structure stop modes, not entry points.
Existing strategies still default to `PATTERN_HIGHEST_HIGH`; this is opt-in.

Validated example:
`visualizer/backend/examples/btc-futures-1h-c3-stop500-activation1000-pullback100.strategy.json`

Use `entry_candle=3` for completed green C1 + red C2 closing below C1 LOW
and entry at C3 OPEN, `doji_filter_enabled=true`,
`doji_threshold_percent=10`,
`take_profit_mode=TRAILING_POINTS`,
`activation_points=1000`, `pullback_points=100`, and
`trailing_ignore_doji=true`. Trading days are Monday-Friday with
`session.blocked_weekdays=[5,6]`; entry window is
`session.windows=[{"start":"00:00","end":"23:59"}]` and timezone
`Asia/Kolkata`. The 1H chart is **display-only**; always retain
`strategy.timeframe="5m"` for 5M intrabar stop monitoring and
close-based trailing updates.

The Futures engine cache identity advances from 16 to 17. Regression
coverage includes actual fill-based stop placement, doji/entry filtering,
trail activation/ratcheting, fee reconciliation, and schema checks.
Market execution remains RESEARCH_ONLY.
