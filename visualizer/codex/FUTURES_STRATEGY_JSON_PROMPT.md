# Copy-paste prompt — BTCUSD Futures Strategy Lab JSON

You are generating **ONE importable BTC Strategy Lab strategy JSON file** for the maintained `visualizer/` app in `rajkumar0rk/Delta-Strategy-Builder`.

**Read the code before generating:** `visualizer/backend/app/models.py` (`StrategyConfig`, `FuturesConfig`, `RuleGroup`, `EntryBehavior`), `visualizer/backend/app/ai_prompt.py`, `visualizer/codex/FUTURES_BACKTEST.md`, and `visualizer/examples/btcusd-futures-research.template.json`. Use actual indicator IDs/operands from `visualizer/backend/app/indicators.py`.

Task: Return **JSON only**, with exactly this outer structure: `{"schema_version":15,"app":"BTC Strategy Lab","strategy":{...}}`. Include the complete valid `StrategyConfig`, not pseudocode, and preserve all fields required by the current source.

## Futures-only semantics
- `strategy.market_type` = `"FUTURES"`. `direction_mode` can be `CALL` for LONG, `PUT` for SHORT, or `BOTH`. CALL entry/exit rules are LONG signals; PUT entry/exit rules are SHORT signals.
- `position_policy` = `"EXCLUSIVE"`: at most one futures position. Signals use **completed** candles; entries and condition exits use the next candle OPEN proxy, not same-candle closes.
- Specify `futures.symbol="BTCUSD"`, `contract_btc=0.001`, `quantity_lots`, `leverage`, `margin_mode`, `maintenance_margin_percent`, `margin_tier_mode` (`FLAT_RESEARCH` default or `DELTA_PUBLISHED_SNAPSHOT` research assumption), `taker_fee_percent`, `gst_percent`, `slippage_bps`, `tick_size`, `slippage_ticks`, `funding_rate_multiplier`, `stop_loss_percent`, `take_profit_percent`, `funding_mode`.
- Futures SL/TP are fractions **of underlying entry price expressed as percentages**, not option premium, not leveraged ROI. Use realistic leverage, size and exit guards. Contract/margin numbers are a dated public *snapshot*, not historical risk validation.
- Funding: `REQUIRE_CSV` means actual `futures_funding.csv` must be present (`timestamp,symbol,funding_rate`, UTC offsets, fraction). `EXCLUDE_WITH_WARNING` explicitly excludes funding and must be labeled incomplete. Never invent funding rates or treat the pre-2025-09-08 minute-by-minute regime as an 8-hour schedule.
- Do **not** enable `call_breakout_retest.require_retest_for_entry` or `put_breakout_retest.require_retest_for_entry`. Option-specific premium controls remain compatibility fields, **not** futures execution controls. Do not add `train_fraction`, `embargo_bars`, `warmup_candles`, `storage_mode`, replay scenarios or job-specific settings under `strategy`; those belong to separate API requests.
- Only use available indicators, confirmed pivots, valid operators and finite numeric inputs. Avoid lookahead or using historical future labels in decisions. Favor fewer high-conviction trades over forced daily entries; avoid guaranteed profit language.

## Validation checklist
1. Confirm JSON parses, outer `schema_version` is **15**, and `StrategyConfig.model_validate(payload["strategy"])` accepts it.
2. Both CALL/PUT lifecycle IDs and indicator references must exist. Do not include dangling condition references or unsupported indicator properties.
3. Risk starting balance, funding assumptions, fee/GST model and max hold are explicit. A successful syntax validation does not prove historical strategy profitability.
4. The current code's `FUTURES` backtest, replay, frozen holdout and internal parity are **RESEARCH_ONLY**; historical Delta executable BBO, mark-price liquidation, INR collateral conversion and actual portfolio tier history are unavailable.
5. Return the **full strategy JSON only**; no explanatory text outside it.

If asked for a suggested research seed, use the repository's futures example as the starting point, preserve its valid schema, and describe performance as **unverified**. Do not fabricate backtest results.
