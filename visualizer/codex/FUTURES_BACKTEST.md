# BTCUSD perpetual futures research — six merged implementation milestones

## Configurable completed higher-timeframe entry gate

Generic futures rule trees support optional `strategy.entry_evaluation_timeframe`: default `"strategy"` (backward compatible) or an equal-or-higher exact multiple of base `strategy.timeframe` from `5m`, `10m`, `15m`, `30m`, `1h`, `4h`, `1D`. Dedicated futures pullback, AMRS and candle-pattern engines retain their own timing and reject this override.

A 5m base with `entry_evaluation_timeframe="1h"` evaluates new entries only on the **first completed 5m candle after** each newly confirmed UTC 1h close. A qualifying order fills at the following 5m open using normal slippage, not retrospectively at the 1h close. Position management, lifecycle transitions, normal exits, stop checks, trailing updates and equity marking still run every 5m; no per-hour cooldown or extra history scan is needed. With `max_entries_per_activation=null`, re-entry remains unlimited across qualifying hourly signals, but cannot repeat multiple times from the same hourly confirmation.

Use 1h RSI(2) and 1h SMA200; for confirmed 1h close vs SMA200, add hidden non-chart-only EMA(1) on 1h (e.g. `close1h`) and use `close1h GT sma200` / `close1h LT sma200`. Raw `close` on a 5m strategy would be the 5m close. Configure 5m fixed 500-point SL and +500/100-point trailing independently with `futures.rule_risk.execution_timeframe="5m"`. No guarantee of parity with TradingView's 1m simulation or exchange fills.

Example: `visualizer/backend/examples/btc-futures-rsi2-sma200-1h-confirmed-5m-gate.strategy.json`. Regression: `visualizer/backend/tests/test_futures_entry_evaluation_gate.py`. Audits respect gate-specific entry eligibility; futures cache identity is 20.

## BTCUSD 1H RSI(2) recovery OR EMA20 invalidation exits (November 2026)

Reuse the existing declarative RuleGroup evaluator for the BTCUSD 1H trend-filtered RSI2 reversal example: `visualizer/backend/examples/btc-futures-rsi2-sma200-1h-ema20-structure-exit.strategy.json`. CALL represents LONG, PUT represents SHORT. Keep all existing entry conditions: LONG RSI(2) < 3 AND 1H close > SMA200 AND 1H close > EMA20; SHORT RSI(2) > 97 AND close < SMA200 AND close < EMA20. Use `call_exit.mode="ANY"` with conditions `rsi2 GTE 70` and `close LT ema20`; use `put_exit.mode="ANY"` with `rsi2 LTE 30` and `close GT ema20`. `mode=ANY` gives true OR logic, including exactly at RSI 70/30, using only the fully completed 1H candle. This replaces earlier two-candle/structure-break exits in this example only. Each exit threshold is independently configurable through the standard condition `value` and the EMA invalidation condition can be removed or disabled via the ordinary rule-tree editor. Do not add unsupported properties, indicators or new engine modes.

Keep fixed 500 BTC-price-point protective stop (`futures.rule_risk.enabled=true`, `stop_mode="FIXED_POINTS"`, `stop_loss_points=500`), `reward_r_multiple=null`, `take_profit_points=null`, `trailing_enabled=false`, `futures.stop_loss_percent=null`, `futures.take_profit_percent=null`. Preserve `EXCLUSIVE`, both unlimited entry lifecycles (`max_entries_per_activation=null`), and 1h indicators `rsi2`, `sma200`, `ema20`. Signal is observed at completed candle close and executed at the NEXT 1H OPEN, including adverse slippage; emergency stop is a separate OHLC high/low price-touch and can preempt the condition exit, with gap risk. No profit activation gate or guaranteed profitable exit is implied. Funding is EXCLUDE_WITH_WARNING and real archive performance has not been established.


## RSI(2) + SMA200 1H EMA20/price-action exit sample (November 2026)

For the 1-hour BTCUSD generic futures strategy, use the existing completed-candle `call_exit` and `put_exit` rule trees; do not introduce a separate exit simulator. Sample: `visualizer/backend/examples/btc-futures-rsi2-sma200-1h-ema20-structure-exit.strategy.json`. Keep `strategy.timeframe="1h"`, RSI(2) and SMA(200) entry filters, `futures.rule_risk.enabled=true`, `stop_mode="FIXED_POINTS"`, `stop_loss_points=500`, and `trailing_enabled=false`. Disable both legacy percentage exits and fixed targets (`reward_r_multiple=null`, `take_profit_points=null`). The initial 500-point protective stop remains active. No profit threshold is necessary before condition exits; the recommended 1H reversal exits are independent of favorable excursion.

For LONG `call_exit`: ALL of (1) current completed 1H `close < ema20`, (2) previous completed 1H `close[1] < ema20[1]`, and (3) current `close < low[1]`. For SHORT `put_exit`: reverse all three comparisons, `close > ema20`, `close[1] > ema20[1]`, and `close > high[1]`. Represent prior-candle comparisons using `Condition.left_offset` and `right_offset`, not an unsupported operator or unconfirmed candle. Once an exit rule confirms at the completed 1H close, the preexisting futures engine fills the exit at the NEXT 1H candle OPEN proxy. The emergency stop remains an intrabar OHLC trigger that can exit sooner, with gap/slippage risk.

This exit intentionally replaces the prior 500/100 point trailing behavior *in this sample only*; existing strategies, schema v15 and shared rule-risk features retain their behavior. The earlier optional profit-activation filter is NOT configured here; the reversal signal may close even a losing position. Exit quality and performance must be backtested on the actual archive. 


## Opt-in 5-minute stop and trailing execution for rule-tree futures

Set `futures.rule_risk.execution_timeframe="5m"` to manage both protective stops and dynamic trailing using chronological 5-minute OHLC, even when the strategy's entry conditions use 1h, 4h, or Daily candles. The default `"strategy"` retains historical behavior. The entry/exit rule-tree still evaluates only completed strategy-timeframe bars; entry fills at the next strategy-bar open. A 5-minute candle first checks its previously active stop (and margin estimate); only if the trade survives can that completed 5-minute candle activate or ratchet the trail, effective from the following 5-minute candle. The 5-minute high/low path inside a bar is unknown: stop-first takes precedence over favorable movement, and gaps receive the legacy adverse proxy. Higher-timeframe ATR-mode trailing uses only the prior **confirmed** strategy ATR snapshot for the current strategy bar; point-mode trailing uses each 5-minute extreme. A missing or incomplete 5-minute child sequence for an exposed strategy bar fails the backtest with FUTURES_RULE_RISK_5M_GAP instead of reverting to coarse OHLC. 5-minute stop updates are research proxies, not tick-level streaming or guaranteed fills. This mode is exclusive to generic futures `rule_risk`; the dedicated candle-pattern engine is unchanged.

## Opt-in fixed BTCUSD stop, activated point trailing and unlimited re-entry (November 2026)

For generic FUTURES rule trees, reuse `futures.rule_risk` (do not enable the dedicated `candle_pattern` engine). Set `enabled=true`, `stop_mode="FIXED_POINTS"`, `stop_loss_points=500`, `stop_buffer_atr=0`, `reward_r_multiple=null`, `take_profit_points=null`, `trailing_enabled=true`, `trailing_mode="POINTS"`, `trailing_activation_points=500`, `trailing_pullback_points=100`, `trailing_source="HIGH_LOW"`. Both `futures.stop_loss_percent` and `futures.take_profit_percent` must be null and pullback/adaptive/candle_pattern disabled. Distances are BTCUSD underlying points, NOT dollar P&L, ticks, percent or option premium. Values must be positive and >= futures.tick_size when active. An ATR indicator is only required for ATR stop/buffer/trailing selections; defaults preserve ATR trailing and SWING stops for old strategies.

For LONG, initial SL = actual simulated entry - stop_loss_points; for SHORT, entry + stop_loss_points. The setup signal is based on a completed strategy candle, entry fills at the NEXT open with adverse slippage/tick rounding. On every subsequent OHLC candle, check the existing stop first (including gaps), then measure the current completed high (LONG) / low (SHORT) to activate trailing once the best favorable excursion >= activation points. The trailing floor is best high - pullback points for LONG / best low + pullback points for SHORT, snapped to a valid price tick; it can only tighten, and becomes executable on the NEXT strategy candle. Activation and stop touches in one OHLC candle are inherently ambiguous; no same-candle hindsight stop is executed. When high/low includes a favorable extreme and the old stop is also touched in that candle, the old stop wins. The legacy execution_timeframe=strategy mode does not do 5m child-bar execution on a 1h strategy; opt into execution_timeframe=5m for sequential child-candle stops and trailing. Historical tick/broker execution is not claimed.

A lifecycle's `max_entries_per_activation=null` means unlimited successful entries during one continuous trigger, without waiting for RSI to reset; numeric 1..100 retains its old capped behavior (default 1). `delay_bars=0`, `cooldown_bars=0`, `max_wait_bars=null` permit the next eligible signal after an exit, still respecting one position at a time, session, no-trade and daily gates. A stop exit candle is never retroactively an entry signal under the existing closed-bar loop; next eligible completed bar can arm the subsequent entry. Applies to OPTIONS lifecycles too because the lifecycle primitive is shared. Existing strategies without these new properties keep their previous behavior.

The implementation is O(1) state per open trade, O(N) overall backtest traversal; no extra OHLC rescans, downloads or dependencies. Futures cache identity increments to 18 so prior cached fills are not reused. Sample `visualizer/backend/examples/btc-futures-rsi2-sma200-point-trailing.strategy.json`, tests `visualizer/backend/tests/test_futures_rule_points_trail_reentry.py`. The sample excludes funding explicitly; include verified funding CSV for funding-inclusive research.


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


Futures is an opt-in market within the existing Strategy Lab UI; OPTIONS remains the default and all existing strategy JSON stays valid. Select **Strategy market → BTCUSD perpetual futures**. Existing bullish CALL conditions act as LONG signals; existing bearish PUT conditions act as SHORT signals. Rule trees, indicators, MTF data, historical warnings, directional no-trade gates, entry lifecycles and score gates are reused. A dedicated `futures` config controls size/fees/funding/price stops, not the option premium controls.

## Research fidelity and sizing

- Historical normalized BTCUSD 5m OHLCV is a **proxy**, not a historical futures order book. There is no broker executable bid/ask or confirmed fill. Signals are determined from completed candle closes; entry and condition exits execute at the next candle's OPEN with user-configured adverse slippage. Stops/targets inspect each subsequent candle's high/low; if both touched, **stop takes priority**; stop gaps fill worse at the candle open.
- Contract default `contract_btc=0.001` BTC per lot, `quantity_lots=1`; P&L is price change × lot BTC × direction (LONG +1, SHORT -1). Configurable assumed taker fee (default 0.05% per side) plus fee GST (default 18%), adverse slippage in bps, leverage (default 5×), margin mode ISOLATED/CROSS and initial collateral notional / leverage. Margin breach uses price extremes and a user-configured maintenance percentage. It is *not* Delta's actual liquidation, risk tiers, wallet/portfolio state or fill price. Leverage changes required collateral, not underlying P&L per unit.
- The existing `risk.max_hold_minutes`, `risk.close_at_session_end`, session windows, daily trade/loss/consecutive-loss limits are used. The separate futures price stop/target settings are percentages of the **underlying futures entry price**, not option premium or leveraged-return percentages.
- This initial futures engine deliberately rejects option-specific profit-protection modes and advanced retest entry overrides rather than silently ignoring them. Existing option premium profit-protection settings are preserved when toggling markets, but they are ignored during futures execution; the futures price stop/target fields are used. Backtest only; no live orders.

## Funding (do not assume zero)

Add `futures_funding.csv` to the selected dataset folder, or the unified archive root. Required columns: `timestamp,symbol,funding_rate`; timestamps must have UTC offsets, symbol `BTCUSD`, and funding_rate must be a **decimal fraction** (0.0001 = 0.01%). The engine currently requires 00:00, 08:00 and 16:00 UTC settlement points for the selected research period; double-check the contract's actual historical funding schedule, rate and mark notional for that period. Missing/duplicate conflicting observations fail when `funding_mode=REQUIRE_CSV` (default). `EXCLUDE_WITH_WARNING` allows a clearly labeled funding-excluded estimate; do not treat that net P&L as exchange-accurate. Funding is approximated using the completed candle close at the settlement clock. Intrabar exits and mark price variance are unknown.

## Limitations

- No historical futures level-2/orderbook data, maker limit order fills, queue position, mark-index spread, changing contract lot specs, real historical tier-dependent margin, automatic top-ups, insurance fund, partial/forced liquidation or futures-specific account state simulation. Estimated maintenance breaches are **research scenario exits**, not exchange liquidations.
- No futures expiry/roll handling (BTCUSD perpetual only). The free historical funding-**rate observation** downloader does not supply verified settlement payment records; the strict settlement importer continues to require futures_funding.csv. Real fees/taxes and funding schedules must be verified against Delta for the traded product/time period.
- Research outputs are stored separately with `strategy.market_type=FUTURES`, `futures_research`, `fee_model.name=DELTA_FUTURES_ASSUMED_TAKER`, and `reliability.grade=RESEARCH_ONLY`. If the last trade stays open when history ends, the position is explicitly unresolved and not force-closed at an invented price. Backtest caching keys include the futures settings and funding CSV fingerprints.
- The initial engine shares normal rule trees/entry lifecycles and score gates. It does **not** yet reproduce every option-engine-specific state-machine or breakout/retest override behavior. Do not compare that feature's outputs as equivalent until dedicated parity tests are added.
- Keep the public BTC history archive untouched when using the engine. The file is read-only; no archive duplication.

## Commands

```powershell
cd C:\projects\workspace\Delta-Strategy-Builder
git pull --ff-only origin working
cd visualizer\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q
cd ..\frontend
npm run test
npm run build
```

## Correctness hardening (merged, October 2026)
- Futures lifecycle states are warmed over pre-range history, and accepted entries consume their selected lifecycle's entry limit/cooldown.
- Funding is applied only after a position survives the corresponding candle; OHLC cannot prove intrabar funding eligibility.
- Stops take priority over estimated intrabar margin breaches unless a breach already exists at candle OPEN. The ambiguous case is counted; this is NOT a Delta liquidation replay.
- Configurable `tick_size` (default research assumption $0.50) and `slippage_ticks` permit conservative fill rounding. These are assumptions, not verified against historical product metadata.
- Futures historical funding schedule, fee tiers, maker executions, risk tier changes, actual liquidation fills and accurate marked equity remain unverified or unavailable. Never present these as modeled.

## Futures stress/replay and accounting upgrade
- Futures replay now varies extra adverse slippage bps, ticks, taker fees and **recorded** funding multiplier. Option-style synthetic half-spread replay remains exclusive to OPTIONS.
- Futures analytics now include a candle-close equity proxy: cash balance + unrealized directional P&L - assumed exit taker fee, including funding in cash. This is not the historical Delta mark price and cannot capture all intrabar drawdown.
- Rejection events identify margin-shortfall versus session/risk blocks; only ANALYSIS/FULL_DEBUG persist compressed decision events.
- `net_pnl_usd` is closed trades only; `return_percent` is cash balance change; `estimated_equity_return_percent` includes marked open exposure. Do not equate them.
- No L1 order book, exchange mark, liquidation tiers or validated funding schedule: RESEARCH_ONLY remains mandatory.

## Milestone 4 — public Delta contract audit (29 Oct 2026)
The public [BTCUSD contract specification](https://www.delta.exchange/contracts) lists 0.001 BTC/lot, $0.50 tick, up to 200x leverage, 0.5% baseline initial margin, 0.25% maintenance margin, size-dependent IM/MM above $100,000 USD notional, 0.05% taker fee, 0.02% maker fee, INR settlement and $5,000,000 position limit. The $5m cap applies to new orders from 23 Aug 2026 ([announcement](https://www.delta.exchange/support/solutions?articleId=80001220837)). This is the **present published contract snapshot**, not date-stamped historic specs.

The futures `margin_tier_mode` defaults to `FLAT_RESEARCH` for backwards compatibility. `DELTA_PUBLISHED_SNAPSHOT` raises required initial/maintenance margin to the published tier minimum at the evaluated notional. This **does not** implement genuine Delta margin, changing account state, INR FX, mark-to-market or liquidation. Recalculate previous futures tests: cache semantics changed.

The [Delta perpetual guide](https://guides.delta.exchange/delta-exchange-india-user-guide/derivatives-guide/docs) reports minute-by-minute funding until 8 Sep 2025 17:30 IST; the current model requires sampled 8-hour funding after the transition. The engine now fails closed with `FUTURES_HISTORICAL_FUNDING_REGIME_UNSUPPORTED` if REQUIRE_CSV spans the earlier minute-by-minute regime, rather than assuming current settlement frequency. EXCLUDE_WITH_WARNING explicitly excludes funding for those older spans. Historical funding rates and USD/INR settlement remain externally supplied/unverified. The present-day contract schedule can change over time; no 2025 funding payments are invented.

## Milestone 5: reproducible historical futures validation
The `POST /api/research/futures-validation` job runs the **existing unchanged Futures backtester** three times: earlier training window; later untouched holdout after configurable embargo; and same holdout under additional adverse price slippage and higher taker fees. It uses strict bar gap handling, original dataset selection (including ARCHIVE), and fixed strategy parameters. The UI button is in Execution replay & robustness. A minimum of 30 bars per segment is required, but 30 **trades** are not guaranteed; small samples receive warnings.
The output separates closed-trade net P&L, fees/GST, funding, profit factor, realized-trade drawdown versus estimated candle-close drawdown, and best/top-three-trades-removed net P&L. This does not train a strategy, search parameter settings, or guarantee profits. Results are only produced if the selected historical dataset exists and the backtests complete. In this GitHub-only environment no user's multi-GB local archive has been run; do **not** cite fabricated profitability statistics. Funding omissions and unresolved end positions are flagged.

## Milestone 6 — independent preview/backtest research parity audit
`POST /api/research/futures-parity-audit` is a cancellable job that runs a strict futures backtest, recalculates chart preview indicators and rules, and checks executed entries against the independently computed completed-candle rule pass and OHLC open. It also verifies stop/exit marker counts, exclusive trade order, gross/net P&L and fee arithmetic. Chart preview lifecycle readiness is **diagnostic** because the preview does not consume executed entry lifecycles; it can warn but does not prove exact executed lifecycle parity. Chart size is limited to 30,000 bars. A PASSED_RESEARCH_ONLY audit is **not exchange certification**: historical actual fills, mark-price draws, funding and USD/INR conversions remain unverified. No numerical validation is claimed unless the user runs the job on an actual archive.

## October 2026 correctness audit
Funding mode `EXCLUDE_WITH_WARNING` now excludes all funding entries, **even if** a funding CSV exists in the selected dataset. `REQUIRE_CSV` alone parses and applies supplied rates. Futures engine cache identity was incremented; regenerate old backtests. The internal parity job now **fails** when any closed trade lacks the chart signal or OHLC entry bar required for comparison rather than warning and reporting a misleading pass. This audit remains internal/research-only.

## Accounting and loader follow-up
The futures cash reconciliation now reports `metrics.cash_reconciliation_residual_usd`; the expected identity is ending cash minus starting cash = sum of closed-trade net P&L + any unresolved position's funding minus paid entry fee. Unresolved position metadata exposes its entry fee, funding and BTC quantity. The internal chart audit checks the **exact configured adverse bps/tick price**, not merely the sign of slippage. Futures cache identity is now version 8; recompute old results. Saved strategy loading from `/api/strategies/{strategy_id}` resolves the strategy directory from the actual project root. These checks remain research-only and do not reconstruct Delta's account ledger or true liquidation.

## Position-aware futures lifecycle trace
Futures backtests now advance *both* enabled direction lifecycles on every completed flat candle (including session, risk, and NO TRADE blocks) and preserve active-direction state while a position is open. Completed trades and unresolved positions carry selected entry lifecycle ID, completed signal timestamp, activation age, delay and eligibility/entry-count snapshot. The internal parity audit validates these reported invariants, but the trace is generated by the engine and **is not a second independently executed lifecycle model**. The engine cache identity is incremented to 9; recompute earlier results to compare.

## Independent lifecycle replay audit follow-up
The futures chart parity job now supplies a warmup-inclusive independently evaluated trigger timeline for each CALL/PUT lifecycle. `futures_lifecycle_replay.py` reconstructs trigger activation, expiry, delay, cooldown, and accepted-entry consumption without calling the execution engine's lifecycle helpers. Recorded signal candle-close and next candle OPEN share a timestamp on contiguous candles: comparison must **not** add another timeframe. The replay checks provenance but does not reconstruct exchange account state, execution eligibility, or actual fills. The existing futures backtest engine cache identity is unchanged because trade decisions are not modified in this audit-only change.

## Full-range compact parity audit
The futures parity API now uses `futures_audit_preview.py` to recompute source indicators and warmup-inclusive raw lifecycle triggers without constructing the normal chart's indicator/study arrays. It retains only trade-entry rule states and corresponding OHLC entry bars, removing the **30,000-candle UI chart rendering cap** from the audit. The normal chart cap remains unchanged. Large date ranges still require real archive coverage, available RAM, valid source data and time to compute; successful audit does not prove broker fills, actual liquidation, or portfolio-level margin. 

## Free historical observation auto-sync (not a settlement ledger)
The **existing** `ARCHIVE` auto-download flag now also triggers `backtest.futures_history` from `visualizer/backend/app/futures_history_sync.py`. The Futures UI enables that flag automatically for an ARCHIVE backtest. The sync reuses `backtest.providers.delta_india.DeltaPublicClient` (public, no API key), downloading only missing completed UTC daily 1-minute shards into `backtest/data/delta-history/futures/{mark,index,funding_rate}/YYYY-MM-DD.csv` and reusing valid shards without re-downloading the already stored BTC OHLCV or option quotes. Correct source symbols: `MARK:BTCUSD`, `.DEXBTUSD`, `FUNDING:BTCUSD`. A response must be time-aligned and mark/index days must be complete; failures leave existing data unchanged. Raw funding *rate* candles are **not actual settlement cashflow records**, and are intentionally **not** automatically converted to `futures_funding.csv`. `REQUIRE_CSV` therefore still requires verified 8h settlement observations and rejects missing data; `EXCLUDE_WITH_WARNING` remains available with funding omitted. These new mark/index candles are stored for future integration; this change does not pretend margin triggers use them yet. No background downloader is scheduled and no historical data was fetched while implementing this feature. Full-range API coverage remains to be tested on the user's machine.

## November 2026 — optional observation sync and DNS error fix

Futures OHLC backtesting uses the existing catalogued BTC 5m `underlying_bars.csv`. It does **not** consume supplemental 1m mark/index/funding-rate observation shards. Two independent **BacktestRequest** flags now control downloads:

- `auto_download_missing_data` (default false): only for `dataset_mode="ARCHIVE"`, repairs uncovered BTC archive dates through `backtest.history_archive`. Required BTC bars must exist for a valid backtest. A genuine underlying-data sync error remains fatal; the engine does not silently fabricate missing candles.
- `auto_sync_futures_observations` (default false): optionally downloads/reuses the separate `futures/mark`, `futures/index`, and `futures/funding_rate` 1m CSV research series. The backtest does not require these. Turning on the BTC archive checkbox does not implicitly enable this secondary sync, and selecting Futures never silently activates either download.

In the UI (Unified archive), enable the first switch if missing BTC archive days should be downloaded. Enable the second only when optional 1m research observations are explicitly needed and network access to `https://api.india.delta.exchange` is working. The two flags belong in the backtest request; **never add them to strategy JSON**. A DNS error such as Windows `[Errno 11001] getaddrinfo failed` affects only a requested download. To run offline on already catalogued BTC bars, turn both switches off. Missing BTC history will still cause preflight failure.

The strict futures settlement ledger is separate: `funding_mode="REQUIRE_CSV"` still requires verified `futures_funding.csv`, and `EXCLUDE_WITH_WARNING` still leaves funding out of P&L. Neither status is changed by downloading indicative 1m funding-rate observations. No funding payments or broker BBO data are synthesized. See `visualizer/codex/CHANGE_IMPACT_MATRIX.md` for request/UI/engine/test companion files.

## November 2026 — automatic cache-first BTC candle availability (Archive mode)

When a user selects an Archive backtest range, the UI enables **reuse existing 5m candles / download only missing candles** by default. BacktestRequest `auto_download_missing_data` remains an explicit request flag (off for external API callers unless supplied); the UI sends it enabled until the user opts out. The process first checks catalog coverage and existing on-disk candle timestamps. If complete, `backtest.candle_repair` returns with **zero Delta API requests and zero writes**. If a segment contains an internal 5m hole, it requests only contiguous missing candles (max 1,440 per API call) and adds them by validated atomic CSV replacement without changing existing candle values. Missing entire catalog intervals for **FUTURES** are appended as BTC-only candle segments; no option products/quotes are fetched. Missing OPTIONS intervals continue the original market-specific contract/quote segment downloader, then verify/repair BTC candles. The explicit **Check / download missing data** action also performs the physical candle check, even when catalog interval coverage is already complete.

The `BacktestRequest.auto_sync_futures_observations` control remains entirely separate, OFF by default; mark/index/rate 1m observations are not used to execute BTC OHLC research. Missing required candles with no network connectivity fail with an actionable error (no fabricated candles or partial overwrite). Incomplete 5m candles and invalid API payloads fail safely, preserve local data and can be retried. Files inside the pre-existing catalog remain authoritative; orphan datasets are never silently used. For raw archival testing see `tests/test_candle_repair.py` and `visualizer/backend/tests/test_cache_first_archive.py`. Schema_version 15 strategy JSON is untouched.

## November 2026: Adaptive Market Regime Strategy (AMRS) — opt-in research mode

AMRS uses `strategy.market_type="FUTURES"`, `strategy.timeframe="5m"`, `strategy.futures.adaptive.enabled=true`. It cannot run alongside `futures.pullback.enabled`, the Options pattern engine, or percent-price `futures.stop_loss_percent` and `futures.take_profit_percent`. Those fields must be disabled/null. Existing Options and Futures paths stay unchanged when AMRS is disabled. The reference schema v15 seed is `visualizer/backend/examples/btc-futures-adaptive-regimes-v1.strategy.json`.

The `ATR_PERCENTILE` indicator computes ATR14 percentile rank against **prior** completed N=720 1h observations (no current-value lookahead). Its exact warmup is N + the ATR convergence horizon; do not apply five times N. The `AdaptiveBreakoutPlanner` reads only completed 1h (ADX14/+DI/-DI, EMA50, EMA200, EMA1 close proxy, ATR percentile) and completed 15m (Donchian20 high/low, ATR14, volume ratio20) signals. Its configurable regime priority is `EXTREME_VOLATILITY` > `COMPRESSION` > `RANGE` > `TREND_UP/TREND_DOWN` > `TRANSITION`. A requested 1h confirmation count requires consecutive equal states; a new unknown or extreme state fails closed. Trend module trades directional 15m Donchian breakout. Compression module can require a **subsequent** completed 15m retest before arming, with configurable ATR tolerance and timeout. All modules share exactly one pending Futures stop-market order and one position.

Adaptive entry reuses `risk_sized_lots` (fees/GST, whole lots, margin, daily budget) and the existing 5m OHLC conservative price proxy. Module-specific frozen 15m structure/ATR stop and R multiple are used per trade. The adaptive trailing stop activates after the **prior completed** 5m close demonstrates at least activation_r of favorable close movement, and updates at the next bar's open by ATR multiple. LONG ratchets upwards only, SHORT downwards only; conservative stop-first handling remains. No tick-path, true mark-to-market liquidation, historical L1/BBO or proven funding settlement precision. All such tests are `RESEARCH_ONLY`.

In-app prompt `visualizer/backend/app/ai_prompt.py` and Codex strategy generation prompt must reuse the actual Pydantic strategy schema. Do not invent `regime` as a top-level StrategyConfig property: it is under `futures.adaptive.regime`. The new `futures.adaptive.trend`, `futures.adaptive.compression`, `futures.adaptive.trailing` sections have validated nested fields. `futures.adaptive` remains disabled by default. See `visualizer/backend/tests/test_adaptive_futures.py`.


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
- Never translate this to legacy `TRAILING_PERCENT`, option premium
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
