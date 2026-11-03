# Strategy JSON generation prompt — BTC Strategy Lab (OPTIONS or FUTURES)

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
- `IndicatorInstance.timeframe` may be `strategy`, `5m`, `10m`, `15m`, `30m`, `1h`, `1D`; explicit indicator timeframe must be an exact multiple of strategy timeframe. No peeking at incomplete higher-timeframe candles, pivots, future labels or future prices. Strategy timeframes are the same except `strategy`.
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
