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
