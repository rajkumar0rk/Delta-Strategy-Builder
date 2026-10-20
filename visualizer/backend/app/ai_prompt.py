from __future__ import annotations
import json
from typing import Any
from .data_store import DataStore
from .indicators import catalog_payload
from .models import AiStrategyPromptRequest, StrategyConfig

OPERATORS = [
    'GT', 'GTE', 'LT', 'LTE', 'EQ', 'BETWEEN',
    'CROSSES_ABOVE', 'CROSSES_BELOW', 'RISING', 'FALLING',
    'GT_BY_POINTS', 'LT_BY_POINTS', 'GT_BY_PERCENT', 'LT_BY_PERCENT',
    'WAS_GT', 'WAS_GTE', 'WAS_LT', 'WAS_LTE', 'WAS_BETWEEN',
    'CROSSED_ABOVE_WITHIN', 'CROSSED_BELOW_WITHIN',
    'COUNT_TRUE_GTE', 'COUNT_CROSS_ABOVE_GTE', 'COUNT_CROSS_BELOW_GTE', 'COUNT_CROSS_EITHER_GTE',
    'SLOPE_GT', 'SLOPE_GTE', 'SLOPE_LT', 'SLOPE_LTE',
]


def _dataset_context(req: AiStrategyPromptRequest) -> dict[str, Any] | None:
    if not req.dataset_id:
        return None
    store = DataStore()
    try:
        p = store.resolve(req.dataset_id)
    except KeyError:
        return {'id': req.dataset_id, 'error': 'Dataset was not found when prompt was generated.'}
    meta = store.metadata(p)
    return {
        'id': meta['id'],
        'bars': meta['bar_count'],
        'available_start': meta['start'],
        'available_end': meta['end'],
        'selected_start': req.start,
        'selected_end': req.end,
        'has_options': meta['has_options'],
        'market_files': ['underlying_bars.csv'] + (['option_instruments.csv', 'option_quotes.csv'] if meta['has_options'] else []),
        'underlying_fields': ['timestamp', 'open', 'high', 'low', 'close', 'volume'],
        'option_quote_fields': ['timestamp', 'symbol', 'bid', 'ask', 'bid_size', 'ask_size', 'volume', 'open_interest'] if meta['has_options'] else [],
    }


def build_strategy_prompt(req: AiStrategyPromptRequest) -> str:
    indicators = catalog_payload()
    schema = StrategyConfig.model_json_schema()
    current = req.strategy.model_dump()
    dataset = _dataset_context(req)

    return f"""You are designing a BTC options strategy for BTC Strategy Lab V15.2 / V16 research mode.

IMPORTANT OUTPUT CONTRACT
- Return ONE valid JSON object only. Do not return Python, Pine Script, prose around the JSON, markdown fences, comments, NaN, Infinity, or invented fields.
- Output shape: {{\"schema_version\":15,\"app\":\"BTC Strategy Lab\",\"strategy\":<StrategyConfig>}}.
- The strategy must validate against the StrategyConfig schema included below.
- direction_mode is CALL, PUT, or BOTH. position_policy=EXCLUSIVE means at most one actual option position is open. CALL and PUT trade actions are BUY or SELL. Separately call_signal_mode / put_signal_mode and call_exit_signal_mode / put_exit_signal_mode are ORDER_ONLY, ALERT_ONLY, or BOTH. ALERT_ONLY evaluates the existing entry/exit rule trees without executing that signal; BOTH keeps the original order path and adds a historical chart alert. Multi-leg spreads are not supported.
- Use only data and indicators explicitly supported below. Do not invent historical IV, Greeks, funding, order-flow, or external/news data.
- alerts is a list of up to 30 historical chart-only AlertRule entries: id, name, message, enabled, direction (CALL/PUT/NEUTRAL), trigger_mode (ON_ENTER/EVERY_BAR), cooldown_bars, source (CALL_ENTRY, PUT_ENTRY, CALL_EXIT, PUT_EXIT, NO_TRADE, CALL_NO_TRADE, PUT_NO_TRADE) and optional condition_id. Alerts REUSE an existing full rule tree or ONE condition from that tree; do not make a separate alert conditions rule tree. Each alert has its own message and enabled toggle. Multiple alerts can fire on the same completed candle without changing trades or P&L. Legacy saved custom alerts may use source=LEGACY_CUSTOM and conditions but do not create new ones. Built-in CALL/PUT entry alerts use call_alert_message/put_alert_message; exit alerts use call_exit_alert_message/put_exit_alert_message. No real-time push notifications.
- Indicators marked chart_only=true are visual research indicators and MUST NOT be referenced by CALL entry, PUT entry, CALL exit, PUT exit, or NO TRADE rules.
- Conditions are evaluated on COMPLETED strategy-timeframe candles. Supported strategy timeframes are 5m, 10m, 15m, 30m and 1h. Aggregated bars are built only from complete groups of downloaded 5m candles. There is no look-ahead.
- Higher-timeframe candles and indicators are anchored to fixed UTC clock-close boundaries, independent of the requested From time. Example: 00:05 + 00:10 form the 10m candle ending 00:10. HTF values become usable only after that HTF candle closes.
- BUY option entry fills use historical ASK + slippage and exits SELL at historical BID - slippage. SELL option entry fills at historical BID - slippage and exits BUY-to-close at historical ASK + slippage. SELL margin requirements are venue/account specific; optional research-only user-calibrated collateral/leverage assumptions are not exchange validated. Never present them as actual Delta initial margin, leverage entitlement, or liquidation.
- Protective stop/take-profit/profit-protection checks are quote driven when applicable.
- A configured NO TRADE group blocks new entries when that group passes. It does not close an already-open position.
- CALL and PUT have separate exit rule groups.
- If both CALL and PUT entry groups pass on the same candle, conflict_policy controls the result.

YOUR JOB
1. Understand the user's trading idea and translate it into supported indicator instances and rule groups.
2. Keep rules as simple as possible; avoid redundant indicators unless there is a clear purpose.
3. Configure CALL entry and PUT entry independently.
4. Configure CALL exit and PUT exit independently.
5. Use no_trade for market states where a new position should be blocked (for example low trend strength or an undesirable momentum zone), if the user's idea requires it.
6. Configure option selection, execution, stop loss, take profit, profit protection, maximum hold, capital/quantity, and trading session.
7. Use unique indicator IDs beginning with a letter. Rule operands use raw OHLCV names or indicator IDs/outputs.
8. Preserve chart-only indicators when they are useful only for visual analysis.
9. If a requested concept cannot be represented with the capabilities below, do not fake it. Omit it and state the limitation only by adding nothing unsupported—the final response still must be JSON only.

RULE GROUP MODEL
A rule group is recursive:
{{
  \"mode\": \"ALL\" | \"ANY\" | \"AT_LEAST\",
  \"min_pass\": 1,
  \"conditions\": [Condition, ...],
  \"groups\": [RuleGroup, ...]
}}
- ALL: every direct condition/subgroup must pass.
- ANY: at least one direct condition/subgroup must pass.
- AT_LEAST: at least min_pass direct conditions/subgroups must pass.
- Empty groups are considered not configured and do not create a signal.

CONDITION MODEL
{{
  \"id\": \"unique-condition-id\",
  \"left\": \"operand\",
  \"operator\": \"operator\",
  \"right\": \"operand or null\",
  \"value\": 0.0,
  \"value2\": null,
  \"left_offset\": 0,
  \"right_offset\": 0
}}
Allowed operators: {json.dumps(OPERATORS)}
- GT/GTE/LT/LTE/EQ compare left with right OR numeric value.
- BETWEEN uses value and value2.
- CROSSES_ABOVE / CROSSES_BELOW compare previous completed candle to current completed candle.
- RISING / FALLING compare the operand with its previous completed value.
- Offsets are candle offsets: 0=current completed candle, 1=previous completed candle, etc.
- GT_BY_POINTS/LT_BY_POINTS require right plus value as the point-distance margin.
- GT_BY_PERCENT/LT_BY_PERCENT require right plus value as the percentage-distance margin relative to abs(right).
- WAS_GT/WAS_GTE/WAS_LT/WAS_LTE ask whether the comparison was true at least once within lookback_bars completed candles.
- WAS_BETWEEN asks whether left was inside value..value2 at least once within lookback_bars.
- CROSSED_ABOVE_WITHIN / CROSSED_BELOW_WITHIN ask whether a cross occurred at least once within lookback_bars.
- For recent-history operators, left_offset shifts the whole search window back. Example: lookback_bars=10 + left_offset=1 means search the previous 10 bars while excluding the current candle.
- Decision records include matched_count and last_match_bars_ago for recent-history rules.
- Raw operands always available: open, high, low, close, volume.
- A single-output indicator is referenced by its indicator id (example: rsi14).
- A multi-output indicator is referenced as id.output (example: macd.macd, macd.signal, bb.upper).
- Raw V15.1 operands also include bullish_close, bearish_close, candle_body and candle_range.
- COUNT_TRUE_GTE counts bars where left > 0.5. Use bullish_close or bearish_close for candle-direction counts. value is the required count and lookback_bars is the window.
- COUNT_CROSS_ABOVE_GTE / COUNT_CROSS_BELOW_GTE / COUNT_CROSS_EITHER_GTE count crosses between left/right within lookback_bars; value is the minimum required count.
- SLOPE_GT/GTE/LT/LTE calculate (current - value N bars ago) / N and compare the points-per-bar slope with value.
- IndicatorInstance.timeframe may be strategy, 5m, 10m, 15m, 30m or 1h. A higher timeframe must be an exact multiple of the strategy timeframe and is usable only after that higher-timeframe candle is complete.
- FORMULA is a safe derived indicator. Its expression may use raw operands and previously calculated indicator operands with + - * / **, parentheses and abs(...). Put dependency indicators before the formula. Examples: (ema9 - ema50) / atr14, atrx.atr / atrx.atr_sma, (close - ema20) / atr14.
- ADX_DMI outputs .adx, .plus_di and .minus_di. CANDLE_STRENGTH outputs body_size, range_size, body_range_percent, body_atr, upper_wick_ratio, lower_wick_ratio, bullish and bearish. ATR_EXPANSION outputs atr, atr_sma, atr_ratio, atr_slope and atr_rising. OVEREXTENSION outputs distance_atr and abs_distance_atr.
- call_big_trend_score and put_big_trend_score create a weighted 0-100 score from entry condition ids. GATE requires the normal entry tree plus score >= threshold; SCORE_ONLY lets score be the directional decision.
- Daily risk controls are risk.max_daily_loss_percent, max_trades_per_day and max_consecutive_losses. They reset at midnight in session.timezone and use closed-trade net P&L after fees/GST.
- session.windows is an ordered list of local-time entry windows. A candle may open a new position when it falls inside ANY window. Each window has start/end HH:MM and may cross midnight. Legacy session.start/session.end mirror the first window only.

SUPPORTED INDICATORS
{json.dumps(indicators, indent=2)}

V15.1 MARKET-STRUCTURE + BIG-TREND SEMANTICS
- STOCHASTIC is the classic price stochastic oscillator, not Stochastic RSI. Its outputs are .k and .d.
- PIVOTS uses left/right confirmation. A historical swing at bar p becomes known only at bar p+right. Use .swing_high_confirmed or .swing_low_confirmed == 1 for a newly confirmed swing, and .last_swing_high/.last_swing_low for the latest known levels.
- DIVERGENCE detects confirmed regular AND hidden divergence using confirmed price pivots. Use .bullish/.bearish for regular divergence and .hidden_bullish/.hidden_bearish for hidden continuation divergence. Hidden bullish = higher price low + lower oscillator low; hidden bearish = lower price high + higher oscillator high. All signals appear only on the second pivot confirmation candle. Supported internal oscillators: RSI, STOCHASTIC_K, STOCH_RSI_K, MACD_HISTOGRAM.
- MARKET_STRUCTURE emits .bos_bullish == 1 or .bos_bearish == 1 only on the first break of each confirmed swing level. .structure_state is 1 after the latest bullish BOS, -1 after bearish BOS, and 0 before any BOS.
- SUPPORT_RESISTANCE clusters confirmed pivot prices only. .support and .resistance are the nearest qualified levels to current price; touch-count outputs are also available.
- These features do not retroactively let a strategy trade at the old pivot candle. Signals become actionable only when they are confirmed.

ENTRY LIFECYCLES (multiple independent lifecycles per CALL and PUT)
Canonical fields are call_entry_lifecycles / put_entry_lifecycles. Each is an ordered list of lifecycle objects:
- id: unique lifecycle id.
- name: human-readable label.
- enabled: whether this lifecycle participates.
- trigger_condition_id: null means the entire directional entry group is the trigger. Otherwise use one condition id inside that side's entry tree (for example MACD > signal).
- delay_bars: minimum completed candles to wait after the trigger arms. 0 allows immediate entry if the full entry group already passes.
- max_wait_bars: optional maximum activation age. This is the key A→B workflow: condition A can arm the lifecycle, then the engine waits up to N candles for the FULL entry group (including condition B) to become true. If the window expires, the lifecycle remains expired until its trigger becomes false and later rearms. null = unlimited while the trigger stays true.
- max_entries_per_activation: maximum successful trades this lifecycle may create while its trigger remains continuously true.
- cooldown_bars: minimum completed candles after a successful entry before another entry from the same lifecycle.
Multiple lifecycles on one side are evaluated independently. If more than one lifecycle is ready on the same candle, list order is priority and only one trade can open because position_policy=EXCLUSIVE.
The legacy call_entry_behavior / put_entry_behavior fields are retained only for older imported strategy compatibility; new strategies should populate the lifecycle lists.
Example: lifecycle 1 arms on MACD > signal and waits up to 3 candles for RSI > 55 + EMA trend; lifecycle 2 independently arms on a BOS condition and waits up to 1 candle for volume confirmation.

DISTANCE / SEPARATION RULES
For any two numeric operands (for example EMA9 and EMA20):
- GT_BY_POINTS: left must be above right by more than value points.
- LT_BY_POINTS: left must be below right by more than value points.
- GT_BY_PERCENT / LT_BY_PERCENT: same idea using percentage separation.
The decision log records actual delta_points and delta_percent for inspection.

OPTION SELECTION
- strike_mode: ATM | ITM | OTM
- strike_steps: integer 0..20
- min_dte_days / max_dte_days
- min_premium / max_premium (nullable)
- max_spread_percent (nullable)
- min_volume (nullable)
- min_open_interest (nullable)
Contract selection is direction aware. CALL maps to CE and PUT maps to PE.

EXECUTION
- max_entry_quote_delay_seconds: 0..3600
- max_exit_quote_delay_seconds: 0..3600
- end_of_data_quote_max_age_seconds: 0..3600 (default 300); stale end quotes leave unresolved exposure, not an assumed exit.
- slippage_ticks: 0..100
- BUY entry = ASK + configured slippage ticks; BUY exit = BID - configured slippage ticks.
- SELL entry = BID - configured slippage ticks; SELL exit = ASK + configured slippage ticks.
- direction_mode: CALL | PUT | BOTH. A disabled direction does not require an enabled lifecycle and is not evaluated.
- call_action / put_action: BUY | SELL. Separate signal modes: ORDER_ONLY | ALERT_ONLY | BOTH, for each entry and exit.
- decision_log_mode: FULL | EVENTS_ONLY. EVENTS_ONLY reduces decision-log volume for faster long-range runs.
- Delta option fees are applied on BOTH entry and exit using this fixed model:
  notional fee = spot × quantity × contract value × 0.01%
  premium cap = option premium × quantity × contract value × 3.5%
  base fee = min(notional fee, premium cap)
  GST = base fee × 18%
  total side fee = base fee + GST
  net P&L = gross option P&L - entry total fee - exit total fee
- Personal income tax is NOT included in per-trade net P&L.

RISK / EXITS
stop_loss.mode:
- NONE
- OPTION_PERCENT: exits when option return <= -abs(value)%
- OPTION_POINTS: exits when option bid <= entry - abs(value)
- UNDERLYING_ATR: direction-aware stop based on entry BTC and the first non-chart-only ATR indicator

take_profit.mode:
- NONE
- OPTION_PERCENT
- OPTION_POINTS

profit_protection.mode:
- NONE
- PEAK_RETENTION: activates at activation_percent; protected floor = peak_return * retain_peak_percent/100
- TRAILING_PERCENT: activates at activation_percent; protected floor = peak_return - trail_percent_points

Other risk controls:
- max_hold_minutes: integer or null
- starting_balance_usd
- quantity_mode: FIXED | BUDGET
- quantity
- budget_usd
- enforce_trade_budget_strict: when true, a valid minimum/fixed quantity is rejected if premium-notional + entry fee exceeds budget_usd. When false, BUDGET mode may step up to the minimum valid quantity even above budget.
- min_quantity and size_increment from the selected contract are ALWAYS enforced; invalid FIXED quantities are rejected regardless of budget setting.
- enforce_cash

SESSION
- timezone is normally Asia/Kolkata
- start/end are HH:MM and may span midnight
- blocked_weekdays uses Monday=0 through Sunday=6

CONFLICT POLICY
- SKIP
- PREFER_CALL
- PREFER_PUT

NO TRADE
- no_trade is a normal recursive RuleGroup.
- If configured and it PASSes on a completed candle, BOTH new CALL and PUT entries are blocked on that candle.
- It is best for underlying/indicator-based avoid conditions. Option spread/volume/OI/premium filtering belongs in option selection because those values exist only after a contract is considered.

DATASET CONTEXT FOR THIS PROMPT
{json.dumps(dataset, indent=2)}

V15.2 ACCURACY & TRUST (BACKTEST SETTINGS ARE NOT STRATEGY FIELDS)
- Indicator warm-up is loaded before the requested range; chart and backtest share completed-candle alignment. Warm-up data never permits entries.
- warmup_candles (default 500) and warmup_policy (WARN or REQUIRE) are BacktestRequest fields only; keep schema_version=15 and do not insert them in StrategyConfig.
- Closed-trade and sampled liquidation-value mark-to-market drawdown are separate metrics; the displayed equity curve is closed-trade equity.
- Open trades without fresh end-of-data quotes remain unresolved. Realized P&L does not include their future outcome.
- Research-only quality metadata flags synthetic quotes, unavailable depth/partial fills, margin and liquidation limitations.
- V16 execution-cost sensitivity is analysis-only; do not invent a strategy.execution_stress property.

V16 PHASE 1 EXECUTION-COST SENSITIVITY
- Post-trade Research Analysis supports hypothetical additional adverse premium fills at entry and exit (0%, 0.5%, 1%, 2%, 5%). This changes only analysis output, not strategy signals or execution.
- Execution stress is NOT part of StrategyConfig; never add a schema field or imply order-book replay, partial fills or margin validation.

DATA LIMITATIONS
- The unified Delta archive is LOW_FIDELITY_SYNTHETIC_BBO: option bid/ask is reconstructed from 1m option candle closes using an estimated spread, and bid/ask sizes are synthetic. Backtest P&L is research/estimated P&L, NOT proof of historically executable fills.
- SELL margin modeling is OFF by default. risk.sell_margin can enable user-calibrated initial_margin_percent, maintenance_margin_percent, max_notional_leverage, collateral_buffer_percent, reserve_exit_fee, margin_mode ISOLATED_ESTIMATE/CROSS_ESTIMATE/PORTFOLIO_ESTIMATE, check_margin_on_quotes. PORTFOLIO_ESTIMATE is a manually provided standalone-account-balance proxy, not Delta portfolio margin computation. It requires user-entered IM/MM rates and explicitly forbids max_notional_leverage; no 29-scenario price/IV stress, portfolio positions/offsets or UCF model. Do not infer a universal leverage value for Delta options. These are scenario-based notional-percent assumptions only, NOT verified Delta margin or exchange liquidation. Enabled margin enforces estimated initial collateral and tests estimated quote-level maintenance breaches; actual portfolio margin, Greeks, orderbook gaps, auto-topup and exchange liquidation remain unmodeled.
- Existing underlying data provides OHLCV.
- Existing normalized option quote data can provide bid, ask, bid_size, ask_size, volume, and open_interest when present in the source rows.
- V15.1 does NOT provide historical IV, delta, gamma, theta, vega, or rho. Do not reference them.
- V15.1 can optionally append uncovered completed UTC days from the repository history archive before a backtest; strategy logic itself never fetches or uses future/incomplete data.
- strategy.timeframe supports "5m", "10m", "15m", "30m", "1h", with completed UTC 5m source aggregation.

V15.1 STATEFUL BIG-TREND FEATURES
- Big Trend score supports BINARY and CONTINUOUS components. CONTINUOUS maps a numeric left operand from zero_at to full_at and gives partial weight between them.
- Score persistence can require threshold hits in N of the last M completed candles; the score itself is available as call_big_trend_score / put_big_trend_score and supports ordinary history/count/slope rules.
- Trend phases are COMPRESSION -> IGNITION -> CONFIRMATION -> BIG_TREND -> EXHAUSTION. Directional phase booleans are normal operands, e.g. call_phase_big_trend.
- Breakout/retest memory can snapshot a configured breakout level, detect a later pullback/hold, expose bars-since-breakout, and block false breakouts until the breakout trigger resets.
- When Require retest before entry is enabled, the breakout trigger condition is treated as a setup-only event at the later retest entry candle; all other entry conditions still have to pass then.
- Shared no_trade remains available, plus call_no_trade and put_no_trade for one-direction-only blocking.
- Fee-aware minimum edge can compare an assumed favorable option-premium move against current bid/ask spread plus estimated Delta round-trip fees. It is an estimate, not a Greeks model.

V15.1 RESEARCH TOOLS
- Identical backtests are cached by dataset fingerprint + selected range + full strategy JSON.
- The UI can sweep one, two, or three numeric strategy/indicator/condition parameters, render 2D heatmaps (and 3D slices), score monthly consistency, and optionally run expanding walk-forward validation.
- Indicator ablation removes dependent entry/exit/directional no-trade conditions, lifecycle triggers and score components, then validates the changed configuration.
- Saved backtest runs can be compared side by side.
- These research tools do not change the strategy JSON schema; they generate controlled variants of it.

CURRENT STRATEGY (use as the starting point unless the user asks for a new blank design)
{json.dumps(current, indent=2)}

EXACT STRATEGYCONFIG JSON SCHEMA
{json.dumps(schema, indent=2)}

Before producing the JSON, internally check:
- every rule operand exists,
- chart_only indicators are not used by rules,
- CALL/PUT entry logic is directionally sensible,
- separate CALL/PUT exit groups are populated only when intended,
- no_trade represents an AVOID state rather than an entry state,
- DTE/premium ranges are valid,
- stop/profit-protection values are coherent,
- no unsupported data is referenced.

Now build the strategy requested by the user and return only the importable JSON object.
"""
