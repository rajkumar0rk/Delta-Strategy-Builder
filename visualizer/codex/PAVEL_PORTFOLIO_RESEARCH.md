# Pavel-style portfolio research (opt-in, November 2026)

## Status and safe scope

The new \`POST /api/research/portfolio-futures\` endpoint queues a cancellable
**research-only** analysis of **existing saved FUTURES run IDs**. Existing
backtests, strategy JSON schema v15, signal generation, fills, options engine,
risk settings and UI remain unchanged. The endpoint returns \`job_id\`; read
\`GET /api/backtests/{job_id}\` and use the existing cancel route.

Request example (replace run IDs with real saved FUTURES runs):

\`\`\`json
{
  "runs": [
    {"run_id": "FIRST_REAL_FUTURES_RUN_ID", "capital_fraction": 0.5},
    {"run_id": "SECOND_REAL_FUTURES_RUN_ID", "capital_fraction": 0.5}
  ],
  "initial_cash_usd": 1000,
  "max_parallel_positions": 2,
  "symbol_conflict_policy": "BLOCK",
  "margin_safety_multiplier": 1.5,
  "max_daily_realized_loss_percent": 2,
  "minimum_correlation_days": 20,
  "max_source_trades": 100000,
  "max_ledger_rows": 500,
  "regime_intervals": [],
  "universe_memberships": []
}
\`\`\`

The request has strict bounded input lengths, valid UTC timestamps and positive
finite numeric parameters. Each run must be a saved Futures run, with a fully
closed trade ledger, reconciled net P&L and the **same source test period**.
A run missing any required field fails rather than silently inventing it.

### What it measures

- Run-specific capital allocation, shared estimated USD free cash, parallel
  position limits, and configurable same-symbol overlap policies.
- Conservative assumed margin reservation at source notional/leverage multiplied
  by the user-selected safety factor. Shared cash charges recorded entry fees
  at entry; released cash uses source recorded net P&L with the entry fee restored,
  preserving fee accounting without double counting.
- Trade-level admission/rejection and rejection reasons, monthly realized P&L,
  entry-time regime attribution, closed-trade drawdown, profit factor, and
  pairwise correlation of **raw, independent daily realized trade P&L**.
- Optional point-in-time interval membership filters. They must be supplied from
  externally verified historical membership data; no current top-coin selection
  is retroactively assumed.
- Strict warnings for funding-excluded source runs and exchange fidelity.

### Important limitations

This **does not regenerate trading signals** after a rejection or execute a
shared, path-dependent portfolio strategy. Accepted fills and P&L are replayed
from individually simulated runs, not sized afresh. There is no real-time
exchange margin/FX/portfolio liquidation, broker bid/ask, tick path,
funding settlement ledger, or intrabar mark-to-market simulation. Opposing
BTC positions can be permitted for research but are *not netted or hedged at an
exchange*. If all inputs lack regime labels the report says UNCLASSIFIED.
Correlation is based on daily close-realized P&L, not true daily portfolio
mark returns. Portfolio realized drawdown is therefore understated when open
positions have large unrealized losses.

Run the new focused regression test and all maintained suites before merging:

\`\`\`powershell
.\.venv\Scripts\python.exe -m pytest visualizer/backend/tests/test_portfolio_research.py -q
.\.venv\Scripts\python.exe -m pytest
cd visualizer/frontend
npm run test -- --run
npm run build
\`\`\`

## Other requested milestones — not completed by this PR

- **Historical execution fidelity:** 1m mark/index and indicative funding-rate
  shards already exist as opt-in downloads, but do not yet drive real P&L.
  Require verified historical settlement data and venue execution observations
  before claiming improved fidelity.
- **Parameter stability:** Existing ResearchSweepRequest, \`run_sweep\`, and
  \`_walk_forward\` provide configurable sweeps, descriptive stability and
  walk-forward. Additional neighborhood heatmaps/futures parameter-specific
  optimizers still need explicit implementation and holdout safeguards.
- **Regime analysis:** Existing AMRS transitions and per-module metrics provide
  some regime observations. This PR accepts *externally computed point-in-time*
  regime intervals for cross-strategy comparison; it does not manufacture
  forward-looking labels.
- **Shared-capital simulation:** A full joint chronological **signal**
  simulator with true position netting, dynamic risk sizing, mark-aware
  margin, funding settlements and reentrant strategy state is a separate
  feature, not delivered here.
- **Offset daily candles:** Not implemented. Must define UTC anchors,
  causally aggregated complete candles, consistent chart/backtest parity
  and stress tests with exact repeated source coverage.
- **Multi-asset point-in-time universe:** BTCUSD saved-run portfolio research
  can enforce supplied universe windows, but does not add arbitrary coins,
  historical listings or ranked top-N constituent downloader.
- **Independent lifecycle/cash correctness:** Existing Futures parity/replay
  auditors remain unchanged. This PR performs independent saved-trade net
  reconciliation; it does not certify exchange-level correctness.

No real historical benchmark was run by this GitHub connector update. Run
CI, review each financial accounting assumption and validate against a local
multi-year archive before using research output for financial decisions.
