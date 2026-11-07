# BTCUSD perpetual futures research — six merged implementation milestones

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
