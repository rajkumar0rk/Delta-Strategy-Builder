# Data and backtest correctness rules

## Unified archive

Default root: `../backtest/data/delta-history`.

`catalog.json` is authoritative. Select only catalog segments whose half-open interval `[start, end_exclusive)` overlaps the requested range. Physical files expected per segment:

```text
underlying_bars.csv
option_instruments.csv
option_quotes.csv
```

Missing completed public-history dates may be downloaded only through `python -m backtest.history_archive sync ...`. Existing catalog segments with missing normalized files should be reported rather than silently replaced.

## Candle semantics

Normalized underlying timestamps are candle-close timestamps. Higher-timeframe candles must be constructed only from complete contiguous 5m source candles. Missing rows mean the higher-timeframe candle is discarded, never synthesized.

Higher-timeframe candles are anchored to fixed UTC clock-close boundaries and MUST NOT depend on the requested From time. For example 00:05 + 00:10 form the 10m candle ending 00:10. Higher-timeframe strategy operands become available only after the complete higher-timeframe candle closes.

Do not convert datetimes to integers and assume nanoseconds. Pandas 3 can use microsecond-resolution datetime storage; use datetime-aware resampling/rounding.

## Pivot/divergence semantics

Confirmed swing pivots are actionable only after their right-side confirmation bars have completed. Divergence may compare oscillator values at historical pivot bars, but the divergence signal is emitted only at confirmation time.

## Option execution

- Long BUY entry: ask + configured slippage.
- Long BUY exit: bid - configured slippage.
- Short SELL entry: bid - configured slippage.
- Short SELL exit: ask + configured slippage.
- Never substitute option candle close when a modeled executable quote is required by the engine.

Delta option fee model per side:

```text
notional fee = spot * quantity * contract_value * 0.01%
premium cap  = option premium * quantity * contract_value * 3.5%
base fee     = min(notional fee, premium cap)
GST          = base fee * 18%
total fee    = base fee + GST
```

Personal income tax is not part of per-trade backtest P&L.

## Research future labels

Trend discovery can inspect future candles only to label whether a historical setup became a BIG or FAKE move. Any feature used to explain/predict the event must come from the label candle or earlier.

## Position sizing

`min_quantity` and `size_increment` from the selected option contract are mandatory exchange-validity constraints. Invalid FIXED quantities are rejected.

`risk.enforce_trade_budget_strict` is user-configurable:

- `true`: reject a valid minimum/fixed quantity when premium-notional + entry fee exceeds `budget_usd`;
- `false`: BUDGET mode may step up to the minimum valid quantity even above `budget_usd`.

This toggle does not disable cash checks and does not model SELL margin/collateral.

## Data fidelity

The public archive is `LOW_FIDELITY_SYNTHETIC_BBO`: option bid/ask is reconstructed from 1m option candle closes using an estimated spread, and sizes are synthetic. P&L/fills are research estimates, not proof of historical executability. SELL margin/collateral/liquidation is not modeled.

## Multi-timeframe warm-up and chart/backtest parity

- Indicator calculations for both chart preview and backtest must include a conservative historical warm-up window **before** the requested range. Do not display warm-up bars or allow warm-up trades.
- Automatically include earlier *catalogued* archive segments as underlying-only warm-up inputs in ARCHIVE/AUTO modes, without expanding the tradable option universe. Explicit SINGLE/MULTI selection remains scoped.
- Flag insufficient **contiguous** warm-up history. No padding or generated candles; incomplete warm-up means early values may depend on dataset start. Backtest requests that support `warmup_policy=REQUIRE` must reject missing history.
- Higher-timeframe OHLC and indicators use actual distinct on-grid base candle close timestamps. Duplicates, missing closes, or off-grid times must not form a complete candle.
- Compare overlapping chart-preview and backtest indicator values at the same timestamp; no access to a higher-timeframe candle before its close.
- A change to these semantics invalidates previous cached backtests. Keep historical results unchanged and identify the behavior change in reports.

## V15.2 and V16 phase 1 consistency

- Backtest and chart preview should share actual completed-candle warm-up. No trades before the requested range. Missing contiguous warm-up gives a warning or a strict rejection.
- Quote-observed liquidation MTM drawdown is an estimate and separate from closed-trade drawdown.
- Do not book stale end-of-range quote exits. Represent unresolved exposure explicitly.
- V16 stress analysis only adjusts existing filled trades hypothetically; it does not re-run entries/stops or imply recorded depth, liquidity, margin, or execution probability.
- Preserve the strategy import schema_version 15 and RESEARCH_ONLY warnings.

## V16 execution stress

Adverse premium scenarios are post-trade analysis only. They do not alter execution, stop timing, depth, historical dataset, margin or saved original trade P&L; synthetic quotes remain RESEARCH_ONLY.


## Optional SELL collateral & leverage (research estimates)
SELL strategies may opt into `risk.sell_margin` with explicitly supplied
initial/maintenance percentages of BTC notional, a maximum assumed notional
leverage (which only imposes an **initial collateral floor**), an optional
collateral buffer, fee reserve and isolated/cross scenario. The field is OFF
by default to preserve existing strategy imports. Enabled scenarios enforce
estimated available collateral when opening positions and can close simulated
positions at observed-quote estimated maintenance breaches. Closed-trade
balance, unrealized quote P&L and fee allowances remain distinct.

**Never label these calculations as Delta-verified margin, leverage, exchange
liquidations, or live-risk numbers.** Delta portfolio margin is risk-dependent;
the actual venue may account for option Greeks, volatility shifts, offsets,
auto-top-up and other account state unavailable to the historical lab.
Historical quote gaps may conceal threshold crossings; liquidation fills and
fees are NOT recreated. Margin research does not convert options SELL into
futures leverage or change option payout algebra. The original $50 trade
budget is only a research limit, not an exchange margin quote.


## Portfolio Margin research selector (V17.1 follow-up)
For Delta India Portfolio Margin accounts, choose **Portfolio Margin — manual
research proxy** in SELL collateral & leverage settings. This selector is
distinct from Cross and Isolated; it treats the lab's one exclusive short
position against the closed-trade account balance, with **explicitly user-entered**
IM/MM notional percentages. To avoid accidental use of prior 5× assumptions,
switching into portfolio mode clears the previous leverage and margin rates.

This is NOT Delta's 29-price/IV-scenario risk margin, portfolio offsetting,
account-wide orders/positions, dynamic short-option floor, UCF or exchange
liquidation. It cannot validate whether Delta would accept an order.
The live authenticated `portfolio_margins` channel exposes account-specific
IM/MM, risk margin and margin floors, but it is not part of this offline lab.
If rates are unavailable, leave margin research disabled: SELL fills remain
margin-unverified. Do not assume 5×/10× option leverage in portfolio mode.
Reference: https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer/portfolio-margin



## Daily level snapshots and alert identities

DAY_LEVELS uses complete raw 5m candles for local calendar ranges, even for
higher strategy/pivot timeframes. A snapshot includes only pivots confirmed by
local midnight and is assigned to candles by OPEN date. Midnight-straddling
candles retain the prior snapshot. Missing days/levels remain unavailable.
Older outside swings are selected newest-first strictly before yesterday,
independently for high and low. Near means the candle interval is within the
configured positive distance; a touch suppresses its same-level near flag.
Optional alert reset_operand rearms on identity changes; warm-up never emits
alerts. See DAY_LEVEL_ALERTS.md for source coverage, outputs and limits.

## DAY_LEVELS calendar vs symbol/session boundaries
`day_boundary_mode=CALENDAR` (default) preserves existing timezone-based
midnight definitions. `SYMBOL_SESSION` currently supports BTCUSD, 24/7,
00:00 UTC research chart convention (not Delta market open or close).
`CUSTOM_SESSION` selects IANA timezone, HH:MM open/close and 0..6 weekdays,
and excludes off-session candles. There is no live symbol trading-hours
discovery API in the lab. Unknown symbols fail closed. Each required
5m close in the previous scheduled session must be present. Shorter custom
sessions and weekend exclusions are supported, but exchange holidays and
early closes are not automatically known. Research consumers must use
the indicator's session labels, not `strategy.session.windows`.
\n## Expiry settlement, sessions and account-margin auditing (engine v174)\n\nOpen options at expiry settle only with an exact matching Delta option settlement payoff imported in `option_settlements.csv`, located either in a selected dataset directory or the unified archive root. CSV columns: `symbol,expiration,settlement_price,source`, optional `index_twap`. `source` must be `DELTA_EXPIRED_PRODUCTS`; `expiration` matches instrument expiration in UTC, `settlement_price` is the **option payoff**, NOT BTC index or futures close. Download expired-products settlement prices using Delta India's public `/v2/products?states=expired` endpoint and preserve each contract's symbol, settlement time and price. Duplicate conflicting records or malformed prices fail rather than inventing values. Settlement uses no bid/ask slippage and a taker-style premium-capped fee + GST. If `index_twap` is missing, the notional portion of fees uses the historical futures close as a clearly disclosed estimate. Missing settlement remains `EXPIRY_SETTLEMENT_UNAVAILABLE`. Backtest cache includes settlement and audit CSV fingerprints.\n\n`risk.close_at_session_end` is opt-in and closes positions at the **last eligible completed strategy candle** before any configured entry-session window ends, using a fresh pre-expiry quote. It respects overlapping/overnight windows. Missing quotes never create fills; `session_end_unfilled_attempts` counts attempts. Session end is NOT a Delta market closing bell.\n\n`account_margin_snapshots.csv` is an optional **audit-only** input for broker-reported historical account metrics: `timestamp,symbol,initial_margin_usd,maintenance_margin_usd,account_equity_usd,source`; `source=DELTA_ACCOUNT_EXPORT`. Enable `risk.sell_margin.audit_against_account_snapshots` to compare nearest matching observations (up to 5 minutes old) with manually assumed margin. It NEVER changes fills, hypothetical margin breaches or entry eligibility: observed past portfolio margin with other positions cannot tell whether a hypothetical backtest order would have been accepted. No full Delta 29-scenario IV/portfolio engine or actual liquidation is implemented.\n
## V175 broker observed account history (not a hypothetical liquidation simulator)
Optional normalized files in the dataset directory or unified archive root:

- `portfolio_margin_history.csv`: timestamp,account_id,currency,wallet_balance,im_w_ucf,mm_w_ucf,blocked_margin,risk_margin,margin_floor,ucf,commission,under_liquidation,source. Source must be `DELTA_PORTFOLIO_MARGINS_CAPTURE` from real contemporaneous broker risk captures.
- `account_fills_history.csv`: fill_id,timestamp,account_id,currency,product_symbol,fill_type,side,size,price,commission,source; optional realized_pnl. Source must be `DELTA_FILLS_HISTORY` from authenticated historical fills, including liquidation/settlement/ADL records.

CSV timestamps require explicit timezone offsets. Conflicts and invalid values fail closed. The results UI reports observed snapshots, broker forced fills, and separate settlement price comparisons. These records cannot reconstruct hypothetical Delta account risk given alternative positions, IV stress, hedges, mark inputs or changing broker liquidation rules. Never interpret missing records as safe trading conditions.

## BTCUSD perpetual futures research
Set strategy.market_type=FUTURES to use the separate candle-OHLC futures backtest, with LONG from CALL rules and SHORT from PUT rules. No option instruments or option quote indexes required. Futures-specific config controls lot BTC quantity, leverage, isolated/cross estimated maintenance, assumed futures taker fees/GST, adverse slippage, price-based stops/targets, and funding with strict CSV coverage. The historical archive is read-only and is not copied. Current futures execution, stop/take ordering, liquidation and funding mark are research approximations; see FUTURES_BACKTEST.md. Options backtesting, options fee model, and old strategy JSON remain compatible.

## Completed UTC daily (1D) timeframes
Options and futures support `strategy.timeframe=1D` and `IndicatorInstance.timeframe=1D`. Daily candles use **288 contiguous 5-minute close-stamped candles** ending 00:00 UTC, and are rejected when incomplete. Daily signals may only act after the day closes; daily indicators on lower-timeframe strategies are forward-filled after their last confirmed UTC daily close. No new historical source is downloaded. Daily strategy backtests inherit existing next-open and risk/session behavior; date windows must cover enough completed 1D bars and warm-up. Existing schema_version 15 remains unchanged. A higher warm-up limit (200000 base strategy candles) is necessary for long daily MTF indicators; long-range requests can consume significant RAM/CPU and require available archived prior days.

## Opt-in BUY-option 15m pattern research (November 2026)
- `strategy.pattern_trade.enabled` defaults to false, preserving all legacy strategies. Requires 5m strategy candles, BUY CALL/PUT, an explicit absolute option delta assumption, and four configured directional 30m setup rule trees (expressed through the regular completed 30m indicator operands).
- Completed 15m pattern events include HAMMER, SHOOTING_STAR, bullish/bearish engulfing, morning/evening star and bullish/bearish marubozu. They preserve the full formation high/low and their close timestamp. Each qualifying event waits for **only the next 1–48 configured completed 5m candles** (default six) to close through that high/low; intrabar invalidations by the opposite pattern extreme take precedence. Strong body/range and prior-volume ratio are required. Normal entry rule trees should contain closed 1H direction filters; ordinary 5m strategy rules must also pass.
- Protective stop is the full pattern low minus the configured buffer for CALL and high plus buffer for PUT. 2R/3R levels are computed from BTC spot at confirmation, not synthetic option premium. A quote-observed BUY-option entry and exit remains required, with existing premium budget, DTE, spread, cash, contract increment and Delta fees plus GST. Risk sizing uses **user-supplied absolute option delta** and a conservative estimated bid/ask spread cost; this is a scenario estimate, not a guaranteed maximum loss. No implied-volatility/Greeks history is fabricated.
- Default first exit is a partial option close at target 1 and the remainder exits at target 2 or earlier pattern stop; optional 2–6 configured target stages use ascending R multiples and fractions totaling 100%, with minimum-lot validation. Since OHLC cannot reconstruct intrabar event order, pattern stops conservatively take priority over targets. Quote availability and expiration must still be checked. These trades remain RESEARCH_ONLY, not verified Delta order fills. No market data downloaded or modified for this code change.

## Project-wide hardening (2026-11-01)
- Legacy JSON behavior remains unchanged by default; opt-in BUY-option pattern confirmation permits 1–48 completed 5m candles, default 6. Pattern types can be selected in the strategy editor without modifying detector logic.
- Pattern option partial exits create separate **execution legs**, not independent closed positions. Research/bootstrap uses combined closed-position P&L and excludes unresolved partial positions; cash/fee reports retain execution legs. Indicator ablation also prunes pattern setup trees and disables pattern mode if removal leaves a required setup unconfigured.
- `STRATEGY_LAB_FRAME_CACHE_MB` (default 64 MB per bars/instruments cache) limits in-process DataFrame caching; set 0 to disable. This is not a total-process memory cap: the working DataFrames, SQLite indexes, result arrays and pandas aggregations still consume memory.
- `STRATEGY_LAB_MAX_WORKERS` default 2, allowed 1..16; `STRATEGY_LAB_MAX_PENDING_JOBS` default 8, allowed 1..1000. Queue overload raises `JOB_QUEUE_FULL`; for a 1GB VPS, start with workers=1, pending=1 and cache=16 MB. These environment settings must be set before the backend process starts.
- Full multi-year performance remains unverified until a real archived benchmark is run. Do not assume that successful unit tests prove suitability for a 1GB VPS.

- Optional `pattern_trade.take_profit_stages` adds 2–6 ordered stages with `r_multiple` and `quantity_fraction` (sum exactly 1); omitting it preserves the previous target_1_r/target_2_r/first_exit_fraction behavior. If a candle closes beyond multiple targets, all reached stages execute against the same available quote; no quote means no fill. Engine cache version 177 avoids stale 2-target results.
- `STRATEGY_LAB_MAX_RETAINED_JOBS` defaults to 200 (10..10000) and trims terminal in-memory job records at submission time; on queue overload `POST` job endpoints return HTTP 429 instead of a generic 500. Pinned disk results are unaffected.

- `STRATEGY_LAB_MAX_BACKTEST_DAYS` defaults to 0 (unlimited); when set to a positive finite day count, both options and futures reject longer requested ranges with `BACKTEST_RANGE_LIMIT_EXCEEDED` **before any automatic download**. This is an admission guard, not a guarantee of RAM usage inside a permitted range; startup warm-up can extend the actual loaded data window.
