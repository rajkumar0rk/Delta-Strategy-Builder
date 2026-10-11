# V16 Phase 1 — Execution-cost sensitivity

Saved-run Analysis reports estimated P&L when additional adverse option-premium
movement is applied to both entry and exit (0%, 0.5%, 1%, 2%, 5%).

This is **post-trade research**, not a rerun of option fills, quote depth,
slippage, trade entry timing, stop triggers, partial fills, liquidation or margin.

Files: backend/app/execution_stress.py, backend/app/analysis.py,
frontend/src/components/ExecutionStressPanel.tsx, AnalysisPanel.tsx,
frontend/src/types.ts, backend/tests/test_v160_execution_stress.py, ai_prompt.py.

- Zero-stress eligible-trade P&L must equal the saved net P&L.
- Missing/unusable fields must be excluded with explicit coverage counts.
- BUY and SELL trades both incur adverse entry and exit movements.
- Recalculate the difference in modeled Delta fee and GST; do not double-charge base fees.
- Preserve LOW_FIDELITY_SYNTHETIC_BBO / RESEARCH_ONLY warnings.
- Keep strategy schema_version 15; execution stress is an analysis response field.
- Changing source calculations requires updating consumers, tests and docs per CHANGE_IMPACT_MATRIX.md.
