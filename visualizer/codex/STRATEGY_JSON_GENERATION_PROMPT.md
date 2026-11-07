# Strategy JSON generation prompt — BTC Strategy Lab (OPTIONS or FUTURES)

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


**Purpose:** Copy the section below into Codex/another coding assistant together with the trading idea. This file is a generation contract, **not** a strategy, execution code, profit claim, or direct LLM integration. The UI's **Generate AI Prompt** feature is implemented separately by `backend/app/ai_prompt.py` at `POST /api/ai/strategy-prompt`; keep its instructions synchronized with this guide.

## Copyable prompt

You are producing **one importable, fully configurable BTC Strategy Lab strategy JSON** for the maintained `visualizer/` project in `rajkumar0rk/Delta-Strategy-Builder`.

**User's strategy idea:** [PASTE RULES HERE]

**Market:** [OPTIONS / FUTURES; if omitted, preserve the provided current strategy's market_type; otherwise state the assumption explicitly before generating only when interaction permits].

**Source of truth, in order:**
1. `visualizer/backend/app/models.py`: `StrategyConfig` and nested models, cross-field validators, `SaveStrategyRequest`.
2. `visualizer/backend/app/indicators.py`: actual indicator kinds, parameter schemas, output names and timeframes.
3. `visualizer/backend/app/rules.py` and `backend/app/ai_prompt.py`: supported rule operators, evaluation, copyable UI prompt.
4. `visualizer/backend/app/engine.py` (OPTIONS) or `futures_engine.py` + `futures_setups.py` (FUTURES): entry/exit/sizing semantics.
5. `visualizer/frontend/src/types.ts`, `defaults.ts`, and feature editors: UI parity.
6. `visualizer/codex/DATA_AND_BACKTEST_RULES.md`, `FUTURES_BACKTEST.md`, `CHANGE_IMPACT_MATRIX.md` and the repository's existing validated examples.

**Output contract**
- Respond with a *single* UTF-8 JSON object and **no Markdown fence, surrounding prose, comments, NaN/Infinity or invented fields**:
  `{"schema_version":15,"app":"BTC Strategy Lab","strategy":{...}}`
- The `strategy` must validate as `StrategyConfig`, not a `BacktestRequest`. Schema version **15** has not been bumped by newer engine milestones.
- Choose `market_type` explicitly. Include deterministic, named indicators; full directional entry and exit groups; separate no-trade rules when useful; explicit session, risk and conflict settings; and a valid enabled lifecycle per enabled direction (unless the implementation documents a different dedicated setup path). `position_policy="EXCLUSIVE"`.
- Use only registered `IndicatorInstance.kind` values and declared outputs. Unique indicator IDs must begin with a letter; reference multi-output indicators as `id.output`. No chart-only indicator in trade/no-trade rules. Rule groups use `ALL`, `ANY`, or `AT_LEAST`; condition operator and operand shape must pass model validation **and runtime checks**.
- `IndicatorInstance.timeframe` may be `strategy`, `5m`, `10m`, `15m`, `30m`, `1h`, `4h`, `1D`; explicit indicator timeframe must be an exact multiple of strategy timeframe. No peeking at incomplete higher-timeframe candles, pivots, future labels or future prices. Strategy timeframes are the same except `strategy`.
- For entry lifecycles, reference a `trigger_condition_id` that actually belongs to the corresponding entry tree; use distinct lifecycle IDs. An alert's `condition_id` must exist in its selected `source` rule tree. Big Trend Score components refer to conditions in that direction's entry tree. Do not invent standalone alert condition trees for new alerts.
- Preserve the user's specified thresholds, direction, trade frequency, stops, exits, trading hours and sizing constraints. Convert ambiguity into **explicit conservative assumptions** rather than inventing capabilities. Never claim win rate or profit factor without a completed measured backtest.

**OPTIONS branch**
- `market_type="OPTIONS"`. CALL/PUT identify option direction, and `call_action`/`put_action` determine BUY versus SELL premiums. Options execution uses selected contract bid/ask quote sides, premium/underlying controls and Delta fee-cap/GST assumptions in `engine.py`; the public historical quote model is often labeled `LOW_FIDELITY_SYNTHETIC_BBO`.
- Keep `risk` option premium stop, target, profit protection, quantity, budget, min lot validity and optional strict budget semantics distinct from the futures settings. SELL option margin is research estimation/audit only, not certified liquidation or account approval.
- `pattern_trade` is **OPTIONS BUY only**, requires `timeframe="5m"`, its directional setup trees and matching pattern parameters; do not turn it on merely because the user mentioned a candlestick pattern.
- `alerts` and `*_signal_mode` can generate historical chart alerts independent of orders; no live notifications/orders are created.

**FUTURES branch**
- `market_type="FUTURES"`, `futures.symbol="BTCUSD"`, CALL=LONG and PUT=SHORT, `call_action="BUY"`, `put_action="BUY"` for compatibility (trade sides come from direction). Futures are perpetual only, use OHLC proxy next-candle-OPEN fills, assumed slippage/ticks, taker fee + GST and estimated risk/collateral. **RESEARCH_ONLY**.
- Configure `contract_btc`, `quantity_lots`, `leverage`, `margin_mode`, `margin_tier_mode`, `maintenance_margin_percent`, `taker_fee_percent`, `gst_percent`, `slippage_bps`, `tick_size`, `slippage_ticks`, `funding_mode`, `funding_rate_multiplier`.
- Legacy stop/target mode: `futures.pullback.enabled=false`, with optional `futures.stop_loss_percent` and `futures.take_profit_percent` measured on **BTCUSD underlying entry price**, never leveraged ROI or option premium.
- Stateful mode: `futures.pullback.enabled=true`, `strategy.timeframe="5m"`, setup timeframe `15m`/`30m`/`1h`; supply non-chart-only `EMA` and `ATR` instances at that setup timeframe and `VOLUME_SMA` at 5m, with IDs matching the three pullback ID fields. Set both legacy percentage stops to `null`, and disable `pattern_trade`. `max_wait_bars * 5 <= 2 * setup_timeframe_minutes`, plus its model bounds. A *subsequent* completed 5m close beyond the frozen HTF setup level triggers a next-open candidate; frozen levels/stops come from the dedicated planner and are **not** made-up indicators. The stateful `PULLBACK_SETUP` path does **not** consume the ordinary `EntryBehavior` lifecycle readiness for entry timing; its ordinary directional rule trees, score, no-trade, session, conflict and exclusive-position gates still apply. Verify this distinction in `futures_engine.py`.
- Both futures modes use the futures `risk.starting_balance_usd`, optional `risk.max_hold_minutes`, `risk.close_at_session_end`, daily circuit breakers and session. These are distinct from option quantity/budget execution.
- `funding_mode="REQUIRE_CSV"` needs verified `futures_funding.csv` (`timestamp,symbol,funding_rate`, UTC offsets, decimal fractions) and a compatible settlement regime; strict replay rejects pre-2025-09-08 12:00 UTC minute-funding history and missing 8h observations. `EXCLUDE_WITH_WARNING` excludes funding **even if a CSV exists**. Auto-downloaded free 1m funding-rate/mark/index series do **not** become verified settlement records and are not yet historical fills or mark-price margin inputs.
- No true Delta futures historical BBO, maker fill/queue, INR collateral/FX, live portfolio margin or liquidation engine. Quote, margin, liquidation and P&L conclusions are scenario estimates; do not add unavailable features to JSON. Keep `call_breakout_retest.require_retest_for_entry` / PUT equivalent off in futures.
- Detailed futures-only guide: `visualizer/codex/FUTURES_STRATEGY_JSON_PROMPT.md`. Existing samples: `visualizer/examples/btcusd-futures-research.template.json` (legacy), `visualizer/backend/examples/btc-futures-stateful-1h-15m-5m.strategy.json` (stateful).

**Do not put API/research-run knobs into StrategyConfig:** `dataset_mode`, `dataset_id`, `start`, `end`, `warmup_candles`, `warmup_policy`, `storage_mode`, `train_fraction`, `embargo_bars`, replay scenarios, history-download flags and job settings belong to separate request models.

**Pre-output verification**
1. Parse the payload with `json.loads`; check `schema_version==15`, `app=="BTC Strategy Lab"`, `market_type` and `position_policy`.
2. Validate `StrategyConfig.model_validate(payload["strategy"])`. Note: Pydantic may silently ignore unknown keys; separately compare all object keys recursively against `StrategyConfig.model_json_schema()`/`$defs` so invented settings are never treated as implemented.
3. Verify operand/output IDs against the actual `catalog_payload()`, cross-reference each lifecycle/score/alert condition, and enforce non-chart-only/timeframe constraints.
4. For futures, verify both protective-exit modes are exclusive, every enabled stateful dependency exists, no unsupported retest override, and funding requirements can actually be met by the selected dataset. A JSON file cannot itself guarantee data coverage.
5. If repository access allows, run the backend validation tests and a focused representative backtest. If a dataset is unavailable, **say results are unverified in a separate conversation**, never fabricate metrics inside the JSON.
6. Return the full importable JSON **only**.

## Opt-in 1H EMA trend / 15M EMA20 STOP-MARKET intraday template

The existing default futures pullback description is the **legacy** `CLOSE_CONFIRM_NEXT_OPEN` mode. For a pending stop-market breakout on the following two completed 15M candles, generate `futures.pullback.execution_mode="STOP_MARKET_INTRABAR"` instead, using the importable seed `visualizer/backend/examples/btc-futures-intraday-1h-15m-stop-market.strategy.json`.

Choose all relevant configuration fields explicitly: `stop_anchor="SIGNAL_CANDLE"`, `breakout_buffer_ticks=1`, `max_wait_bars=6` base 5M candles, `stop_buffer_atr=0.1`, `reward_r_multiple=2`, `require_volume=false`, optional `trend_fast_ema_id`/`trend_slow_ema_id`/`trend_close_indicator_id` (together and with 1H EMA50/200/1), `trend_crossover_block_bars=3`, and `cancel_on_trend_invalidation=true`. Keep normal directional rule trees limited to completed 1H trend conditions. Risk equity sizing `equity_risk_percent=0.5`; daily starting-day realized loss limit `risk.max_daily_loss_percent=1` plus remaining-risk allowance; no max hold or EMA exit. Entry session 14:00–21:59 Asia/Kolkata (22:00 exclusive); independent `futures.force_exit_time="23:45"`. Include `extra_half_spread_bps` only as a clearly assumed proxy cost. The two legacy futures percentage protective-exit fields MUST be null.

The stop-market path triggers from subsequent 5M high/low (not a breakout close), fills conservatively at stop trigger or worse gap open with tick/bps adjustments, and processes protective stops/targets in the same candle with unfavorable ordering when OHLC chronology cannot be known. Do not present it as historical tick execution. The internal parity audit flags this path as partial research parity, not exchange-verified. Preserve the legacy mode for already-saved JSONs, schema_version 15, and bound all order state. Prefer changing configurable IDs/settings over creating duplicate strategy-specific engines.

## Shared futures/options 1H/15M stop-mode instructions

The completed-HTF signal planner, 1H EMA trend gate, underlying stop trigger/expiry and calendar force-exit clock are reusable, but market execution remains separate. For `OPTIONS` use `options_pullback.enabled=true` only when trading BUY CALL or BUY PUT (not SELL), with a 5m strategy timeframe and valid 15m EMA20/ATR14 indicators, and optional matching 1h EMA50/EMA200/EMA(1) IDs. Configure `stop_anchor=SIGNAL_CANDLE`, `underlying_tick_size=0.5` (research assumption), `breakout_buffer_ticks=1`, `max_wait_bars=6`, `stop_buffer_atr=0.1`, `reward_r_multiple=2`, `size_mode=RISK_EQUITY`, `equity_risk_percent=0.5`, `trend_crossover_block_bars=3`, `cancel_on_trend_invalidation=true`, and independent `options_force_exit_time=23:45` with entry windows 14:00–21:59 Asia/Kolkata and `risk.max_daily_loss_percent=1`. Disable `risk.stop_loss`, `risk.take_profit`, `risk.profit_protection` modes and options `pattern_trade` in the opt-in variant.

The underlying stop can be touched inside a 5m BTC bar, but option selection/quote execution occurs only **at/after that completed bar**, and every fill requires a real eligible option quote. The underlying ATR stop and BTC 2R target are NOT guaranteed premium-risk multiples; actual net P&L is calculated from quoted premiums, fees/GST and option contract size. BUY premium-at-risk sizing assumes total paid premium plus two fee allowances and enforces real min/step rules; SELL premium-risk remains unsupported. Missing/expired quotes do not imply fills. Do not import futures leverage, funding, margin or mark price concepts into OPTIONS. Use `visualizer/backend/examples/btc-options-intraday-pullback.strategy.json` and `visualizer/codex/OPTIONS_PULLBACK_BACKTEST.md` as the authoritative options reference.

The existing future-specific `futures.pullback.execution_mode=STOP_MARKET_INTRABAR` stays implemented and unchanged. Both modes remain RESEARCH_ONLY and use schema_version 15. New shared helper implementation: `visualizer/backend/app/shared_execution.py`, with market-specific option/futures fee and fill paths.

## Futures history sync is a backtest request preference, not strategy JSON

Futures backtest needs catalogued BTC OHLC bars, but does **not** require automatically downloading separate 1m mark/index/funding-rate observations. Never put `auto_download_missing_data` or `auto_sync_futures_observations` under StrategyConfig. In an ARCHIVE BacktestRequest only, enable `auto_download_missing_data` to repair missing BTC archive bars, and enable `auto_sync_futures_observations` independently to fetch optional separate observation shards. Both default false. `futures.funding_mode=EXCLUDE_WITH_WARNING` excludes funding from P&L without requesting 1m observation sync; `REQUIRE_CSV` still needs an actual settlement CSV and cannot be satisfied by rate-observation downloads. Treat Windows DNS errors as explicitly requested network download failures, not strategy signal failures.

## Adaptive BTC Futures strategy (AMRS; November 2026)

When asked to create an adaptive 1h trend/volatility classifier with separate trend-continuation and compression-breakout Futures strategies, use the implemented **opt-in** `strategy.futures.adaptive` structure in the current `StrategyConfig.model_json_schema()`. Do not invent a top-level regime key or put research request flags inside StrategyConfig.

Use 5m base timeframe, `market_type=FUTURES`, `position_policy=EXCLUSIVE`, `futures.adaptive.enabled=true`, `futures.pullback.enabled=false`, `futures.stop_loss_percent=null` and `futures.take_profit_percent=null`. Require 1h EMA50/EMA200/EMA1(close), ADX_DMI(14), ATR_PERCENTILE(14,720), plus 15m Donchian(20), ATR(14), VOLUME_RATIO(20). These must be non-chart-only and all ID/timeframe references must be consistent. Configure regime ADX and ATR percentile thresholds, 1h confirmation candles and EMA slope; trend continuation and compression modules independently control volume ratio, breakout/retest, ATR stop buffer and 3R target. The compression retest uses a later completed 15m candle, not same-candle high/low. If enabled, ATR trailing activates after 2R and uses only previous closed 5m information. Fees, GST, slippage, risk-based whole-lot sizing, session and daily risk caps remain unchanged. No automatic live orders or guaranteed profit. Use the actual reference `visualizer/backend/examples/btc-futures-adaptive-regimes-v1.strategy.json`. No ATR_PERCENTILE output is valid without sufficient prior lookback history.

All adaptive scenarios are conservative OHLC-based RESEARCH_ONLY studies. Configure funded position assumptions with verified data or `EXCLUDE_WITH_WARNING`; do not represent optional observation rates as settled funding cashflows.
