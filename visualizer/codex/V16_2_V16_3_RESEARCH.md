# V16.2–V16.3 research extensions — working branch

## V16.2: complete low-fidelity scenario replay
POST `/api/research/execution-replay` takes a dataset selector, start/end,
strategy, up to 12 adverse execution combinations (extra half-spread percent
and extra slippage ticks). Runs with `storage_mode=COMPACT` and separate cache
identities. Each scenario reruns entry selection, premium/spread screening,
sizing, fee-aware edge gates, stop and profit protection, exit decisions,
quote-sampled mark-to-market and P&L. The exact 0/0 scenario is included.

The extra half-spread is calculated as a percentage of the source bid/ask
midpoint and widens both sides symmetrically, in addition to modeled
historical spread. Slippage ticks are additional to the saved strategy.
This is hypothetical sensitivity, **not recorded L1 or depth**, no queue
model, fill probability, partial fills or actual live market validation.

## V16.3: closed-trade robustness
The Analysis API now includes `robustness_v163` with seeded, reproducible
independent trade-P&L bootstrap (1,000 replications by default), p05/median/p95
net P&L, p95 simulated sequence drawdown, loss-frequency *within the
assumed bootstrap*, top-one and top-three trade dependence, and
net-without-outliers. This is NOT a probability of future returns; it
does not re-price option quotes and excludes unresolved positions.

Sweep results include parameter-neighborhood descriptive statistics (number
of positive cells, median/worst/best net). These are in-sample. The existing
expanding walk-forward research remains available.

POST `/api/research/holdout` runs a **frozen** strategy on earlier training
dates and an unseen later test period with an optional embargo in strategy
bars. It reports independent metrics and bootstrap diagnostics; the
account balance resets for each period and a persisted position is not
transferred across the split. This is not nested model-selection validation.

## Scope and verification
UI: new V16.2/V16.3 research panel and Analysis robustness readout.
The current V16.1 data-quality safeguards and expiry finality carry over.
No V17 live feed/real-time paper trading implemented.
Run backend pytest and frontend build/Vitest before historical review.
