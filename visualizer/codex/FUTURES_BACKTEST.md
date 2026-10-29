# BTCUSD perpetual futures research — first implementation

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
- No futures expiry/roll handling (BTCUSD perpetual only). No funding-rate downloader: importer is a normalized CSV, not an assumption. Real fees/taxes and funding schedules must be verified against Delta for the traded product/time period.
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

## Correctness hardening (review branch, October 2026)
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
