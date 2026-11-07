# Copy-paste prompt — BTCUSD Futures Strategy Lab JSON

## v2: stronger 1H BTC Futures bullish reversal with adaptive structure exit (November 2026)

Import `visualizer/backend/examples/btc-futures-1h-bullish-reversal-confirmed-v2.strategy.json`. The older `btc-futures-1h-bullish-reversal-structure-exit.strategy.json` is retained as an unchanged baseline.

- Long only. Require three consecutive completed lower highs AND lower lows, including a bearish last setup candle, close below its predecessor's open, and at least two bearish candles in the three-bar down sequence.
- Entry alternative A: immediately completed bullish engulfing of previous red body; fill next 1H open.
- Entry alternative B: prior completed doji (body/range <= 10%) or bullish hammer (body/range <= 40%, lower wick >=50%, upper wick <=20%) after the bearish sequence, plus a **later** completed bullish candle closing strictly ABOVE the pattern HIGH; fill next 1H open. All thresholds and historical offsets are editable via ordinary nested JSON rules. Never use a still-forming candle or a later bar for pattern detection.
- Initial stop: lowest low of the last two completed bars (reversal/confirmation window), using existing `rule_risk.stop_mode=SWING`, `swing_lookback_bars=2`. Includes next-open gap protection and estimated fees in risk sizing.
- New opt-in `rule_risk.max_stop_distance_percent` and `max_stop_distance_atr` reject entries where the executed entry-to-initial-stop price distance exceeds either cap. ATR caps require a non-chart-only strategy-timeframe ATR indicator; validated on import.
- Exit: close below the immediately preceding 1H LOW, OR two consecutive lower highs **and** lower lows. A single non-higher-high is not sufficient.
- `rule_risk.condition_exit_activation_r=0.5` arms the exit tree after a completed close reaches +0.5 times initial price risk; before arming the initial protective stop and margin/time exits still apply. Arming stays active afterward. `breakeven_activation_r=1.0` ratchets stop to entry (plus `breakeven_offset_ticks`) **only** after a completed close reaches +1R. Protective stop remains active intrabar, ratchet applies to next bar; stop gaps and fees mean realized net loss remains possible.
- `reward_r_multiple=null`, `take_profit_points=null`, trailing disabled. Example starting defaults: 0.5% equity risk, max stop distance 1% of fill and 3× frozen ATR, 72-hour time exit. No fixed take-profit; this is not guaranteed to outperform the previous strategy.
- Existing saved strategies retain null/zero defaults for every new field, and old execution behavior remains unchanged. Futures research remains OHLC-proxy only. Cache version 180.


## Example: 1H bearish continuation to bullish reversal, then exit on failure

File: `visualizer/backend/examples/btc-futures-1h-bullish-reversal-structure-exit.strategy.json`.
This is a **LONG-only** strategy, not the former EMA/ADX breakout + fixed 3R preset.

- Bearish setup on the completed **red candle** immediately preceding the reversal candle: its high is strictly below the high two candles back, its close is strictly below the open two candles back, and its low is strictly below the low two candles back.
- The current completed 1H candle must confirm one of: (1) bullish body-engulfing of the previous red candle (`open <= previous close` and `close > previous open`); (2) bullish/flat doji (body/range <= 10%, close >= open and close > previous close); or (3) bullish hammer (body/range <= 40%, lower wick >= 50%, upper wick <= 20%, close > previous close). All thresholds are ordinary configurable rule values, and `CANDLE_STRENGTH` is an existing indicator.
- LONG executes at the next 1H OPEN, subject to existing gap guard and an initial protective stop at the completed reversal signal candle LOW. Fixed R/point profit targets and ATR trailing are disabled. Daily risk, execution costs, margin estimates and one-position-only operation remain enabled.
- While long, a completed 1H candle sustains bullish structure only if `high > high[1]`, `close > open[1]`, AND `low > low[1]`. The `call_exit` rule is the **OR of their failures**, using `LTE`, so any one failure schedules an exit at the next candle OPEN. Stops can exit earlier inside the research OHLC candle.
- No new schema keys, candle scans, rule operators, or execution engine changes are required. The existing generic rule evaluator is closed-candle/no-lookahead and uses bounded constant-offset comparisons. This is a candidate model, not proof of a real market trend change.


## Completed reference-candle stop and entry-gap guard (November 2026)

Use the opt-in existing `futures.rule_risk` planner; do not invent another futures mode.
- `stop_mode=SIGNAL_CANDLE`, `stop_candle_offset_bars=0`: the completed entry signal candle (the **previous** candle when the subsequent candle OPEN fills the entry). Offset 1 selects the completed candle immediately before that signal. Valid offsets: 0..200, available history required. Nonzero offset with SWING or ATR mode is invalid.
- `max_entry_gap_percent=null`: legacy no-gap-limit behavior. Otherwise 0..100 is the maximum absolute distance in percent between the frozen signal CLOSE and adverse-slippage-adjusted next OPEN fill. Reject larger gaps. Stop-protectiveness, risk budget, whole-lot sizing, margin, fees, and funding checks still apply.
- `reward_r_multiple=3`, `take_profit_points=null`: target three times the **actual executed entry-to-frozen-stop** price difference, with conservative tick rounding. No guarantee of net 3R after fees, GST, slippage, stop gaps or liquidation. Existing stop-first same-candle convention applies.
- Example: `visualizer/backend/examples/btc-futures-1h-previous-candle-3r.strategy.json`. A 1h EMA50/200 + ADX14/DMI trend filter and preceding-high/low close breakout is evaluated on completed 1h bars. Entry is next 1h OPEN; long SL at previous 1h candle low, short SL at its high; 3R target. Uses one-position-only and optional 0.5% next-open gap guard.
- This is a deterministic OHLC simulation, not actual tick-sequenced exchange execution. Gap-fill limits do **not** cap stop losses. Existing serialized strategies default the new fields to `0` and `null` and keep their original behavior. Backtest cache version bumped to 179.


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
