# Change checklist for Codex

Before coding:

1. Read `AGENTS.md` plus the relevant backend/frontend nested AGENTS file.
2. Identify whether the task changes trading semantics, data semantics, persistence only, or UI only.
2a. Read `codex/CHANGE_IMPACT_MATRIX.md` and identify all companion files, consumers, documentation and tests that might also require updates.
3. Check backward compatibility for saved strategy JSON and old result folders.

Before finishing:

1. Add or update focused tests.
2. Run the backend test suite for backend changes.
3. Run frontend build/type checks for frontend changes when dependencies are present.
4. Confirm no future information entered strategy decisions.
5. Confirm archive files were not modified unless the requested task is an explicit archive sync.
6. If engine behavior changed, consider cache-version bump.
7. If result persistence changed, confirm both legacy and V15/V15.1 compressed artifacts remain readable.
8. Summarize exactly what changed and any limitations; do not claim unrun verification.
8a. Confirm each applicable `codex/CHANGE_IMPACT_MATRIX.md` companion was inspected; state modified, inspected/unchanged, and deferred files separately.

9. If candle/indicator timeframes changed, run start-time-invariance tests and a datetime64[us] HTF indicator test.
10. If position sizing changed, test min quantity, size increment, strict-budget ON and OFF.
11. If result creation changed, test two same-name runs created immediately produce different directories.

12. For indicator or timeframe changes, test 15m/30m/1h aggregation, duplicate/missing/off-grid timestamps, no future leakage, completed-boundary alignment, and chart vs backtest value parity.
13. If warm-up behavior changes, test archived cross-segment history, missing-history warnings, historical cache invalidation, and identical overlapping values after sufficient warm-up.

## V15.2 + V16 regression checks

- Compare HTF chart/backtest values and strict/non-strict warm-up; test stale and fresh final quotes.
- Verify mark-to-market bid/ask fee accounting and distinguish unresolved from realized P&L.
- Test gzip analysis compatibility and paired execution-rejection deduplication.
- Confirm all ablation references validate after indicator removal.
- For V16 stress, 0% must match baseline; adverse stress should lower BUY/SELL P&L, skip invalid trades and report coverage; run backend tests + frontend build.
- Check codex/CHANGE_IMPACT_MATRIX.md and keep AI prompts/schema in sync.

## V16 execution sensitivity verification

Check zero-stress P&L preservation, adverse BUY/SELL cost, invalid-trade coverage, fee/GST differences and frontend build. Keep strategy schema_version 15 and V16 analysis separate from fills.
