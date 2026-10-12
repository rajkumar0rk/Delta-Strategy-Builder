# V16.1 correctness hardening (working branch)

Scope: historical research reliability only; not V16.2 execution replay, V16.3 research, or V17.

## 5m candle grid
BacktestRequest.bar_gap_policy is REQUIRE by default. Preflight compares
actual UTC 5-minute candle-close timestamps to the exact expected grid and
reports missing and off-grid examples. WARN is an explicit research override
for incomplete underlying history, never an implicit claim of completeness.
The UI exposes the policy next to result storage.

## Lifecycle and chart parity
The backtest now replays entry-lifecycle trigger state over warm-up candles
without allowing pre-range orders. Chart lifecycle diagnostics do the same
before clipping the visible date range. This fixes false reset/re-arm at From.
Other chart overlays and conditional fills are still research-only.

## Expiration and unresolved positions
Historical entry quotes at or after contract expiration are rejected.
Quote-driven protective stops ignore post-expiry quotes. All simulated exits
reject post-expiry execution. At end-of-range, an open expired option whose
settlement is unavailable remains unresolved with
EXPIRY_SETTLEMENT_UNAVAILABLE; its P&L is not fabricated by recycling a quote.
An unexpired position without a sufficiently recent quote remains unresolved
with NO_FRESH_FINAL_QUOTE. These safeguards do not model actual
exercise/settlement or broker liquidation.

## Limitations and verification
- Synthetic options quotes do not validate executable bids/asks or fills.
- Quote gaps can prevent fills, stops, or exits; do not interpolate L1.
- Re-run backend pytest and frontend build/test locally before treating these
  changes as verified. Historical-output comparisons are still required.
- Old saved strategies remain valid; engine cache version is bumped.
