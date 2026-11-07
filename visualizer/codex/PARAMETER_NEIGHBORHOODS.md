# Parameter neighborhood stability — research only

The existing `POST /api/research/sweep` now includes additive `parameter_neighborhoods` results. This reuses existing completed backtest sweep rows: **no new backtests, no second optimizer and no strategy JSON migration**. The request optional field `stability_min_trades` defaults to 10 (1–10,000). Results include parameter coordinates, trade count, immediate axial neighbors, positive-neighbor ratio, median/worst neighbor net P&L, isolated peaks and positive plateaus. Invalid and low-sample cells are excluded from stability claims. Input axis values must be unique.

The ResearchPanel displays a minimum-trades control and a neighborhood table. Existing heatmap, sweep sorting, walk-forward, ablation, rules and futures execution remain unchanged.

**Caveats:** Positive neighbor plateaus are *in-sample descriptive evidence*, not profitability, independent validation or any prediction. Neighbors use the input value order, not Euclidean parameter distances. The minimum trades threshold does not guarantee statistical significance; use the existing expanding walk-forward/holdout and conservative execution replay. More complex methods (cross-validated parameter sensitivity, regime-conditioned OOS, bounded auto-optimizer and full futures funding/mark-price execution) remain separate future milestones.

## Verification

Run focused and integration tests on the actual repository checkout:
```powershell
Set-Location visualizer/backend
python -m pytest tests/test_parameter_neighborhood_stability.py tests/test_research_v5.py -q
Set-Location ../frontend
npm run test -- --run
npm run build
```

No archive data was downloaded or changed. No historical benchmark result is claimed. Inspect the GitHub Actions checks before merging.
