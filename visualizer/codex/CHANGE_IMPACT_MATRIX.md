# Change Impact Matrix — mandatory companion-file review

> **Applies to every Codex/AI change under `visualizer/`.** Read this file with `../AGENTS.md`, `ARCHITECTURE.md`, `DATA_AND_BACKTEST_RULES.md`, and `CHANGE_CHECKLIST.md` **before editing**. A change is not complete merely because the primary file compiles.

## Mandatory workflow

1. **Identify the change surface.** List the primary file(s), consumers, producers, API/config contracts, persisted artifacts, and related tests. Search actual imports/usages in the current checkout; this table is an aid, not a substitute for code search.
2. **Check the matching rows below.** Inspect every listed companion file. **Modify it only when required** by the change; never make dummy edits or blindly update every file.
3. **Keep all interfaces in sync in the same change.** When behavior, API response, defaults, strategy JSON, persistence, or UI changes, update affected callers, tests, docs, and AI prompt together. Prefer backward-compatible migrations for saved strategies and results.
4. **Keep data and trading invariants.** Completed candles only; no future data in decisions; UTC HTF close boundaries; no fabricated option quotes, liquidity, margin, or Greeks. Do not modify the historical archive for an ordinary app change.
5. **Invalidate stale backtests when semantics change.** Inspect the engine/cache identity before changing calculations, fills, fees, signals, or selection. Bump cache version when old results are no longer equivalent; do not silently reuse them.
6. **Verify.** Run focused tests first; then backend tests / frontend build for affected code. Check that an existing strategy JSON and an old stored run still work when their contracts are affected. Never claim unrun tests passed.
7. **Report the impact.** In your final change summary state: primary files, companion files updated, companion files inspected but not needed (when material), tests run, migrations/cache impact, and unresolved limitations.

## File-to-file impact map

Paths below are relative to `visualizer/`. `→` means **inspect and update if the interface or behavior is affected**.

| When changing… | Inspect/update these companion files | Verify |
|---|---|---|
| **New indicator / indicator output / parameter / timeframe** — `backend/app/indicators.py` | `backend/app/models.py` (validation), `backend/app/rules.py` (operands if affected), `backend/app/ai_prompt.py`, `frontend/src/components/IndicatorManager.tsx`, `frontend/src/types.ts`, `frontend/src/defaults.ts`, `frontend/src/components/RuleBuilder.tsx`, `codex/DATA_AND_BACKTEST_RULES.md` | `backend/tests/test_indicators.py`, `test_rules.py`, `test_ai_prompt.py`; HTF close/no-look-ahead tests |
| **Rule operator / condition / nested group** — `backend/app/rules.py` | `backend/app/models.py`, `backend/app/ai_prompt.py` (allowed operators and examples), `frontend/src/components/RuleBuilder.tsx`, `frontend/src/types.ts`, `frontend/src/defaults.ts` | `backend/tests/test_rules.py`, `test_models.py`, `test_ai_prompt.py` |
| **Strategy config, schema, default or migration** — `backend/app/models.py` | `frontend/src/types.ts`, `frontend/src/defaults.ts`, affected React editors, `backend/app/ai_prompt.py`, `backend/app/engine.py`, `backend/app/main.py`, saved example JSON in `examples/`, documentation | `backend/tests/test_models.py`, `test_ai_prompt.py`; old strategy import; frontend type/build |
| **Backtest signals, position lifecycle, entry/exit, stops, sizing, fees or execution** — `backend/app/engine.py` | `backend/app/models.py`, `backend/app/data_store.py` (quote availability), `backend/app/analysis.py`, `backend/app/storage.py`, `frontend/src/components/RiskOptions.tsx`, `Results.tsx`, `EquityDrawdown.tsx`, `frontend/src/types.ts`, `backend/app/ai_prompt.py`, `codex/DATA_AND_BACKTEST_RULES.md`, cache version | `backend/tests/test_engine_v*.py` (applicable versions), `test_v15_1_correctness.py`; fill/fee/quantity/stop regression; cached vs fresh comparison |
| **Candle aggregation, warm-up, dataset selection, quote parsing/indexing** — `backend/app/data_store.py` | `backend/app/indicators.py`, `backend/app/engine.py`, `backend/app/archive_sync.py`, `backend/app/models.py`, `backend/app/analysis.py`, `backend/app/ai_prompt.py`, `codex/DATA_AND_BACKTEST_RULES.md`, cache identity | `backend/tests/test_v15_1_correctness.py`, `test_v13_archive_and_discovery.py`, `test_v14_archive_sessions.py`; missing-candle, UTC-boundary, start-date invariance tests |
| **Delta archive coverage/downloading** — `backend/app/archive_sync.py` | `backend/app/data_store.py`, `backend/app/main.py`, `frontend/src/api.ts`, archive-related UI in `frontend/src/App.tsx`, repository `../backtest/history_archive.py` (read/inspect only unless explicitly requested), documentation | Archive/preflight tests; prove no unintended writes to `../backtest/data/delta-history` |
| **FastAPI routes, request/response types, errors** — `backend/app/main.py` | `backend/app/models.py`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/App.tsx`, affected frontend components, API documentation | Endpoint tests; frontend build and one end-to-end request |
| **Jobs, cancellation or progress status** — `backend/app/jobs.py` | `backend/app/main.py`, `backend/app/engine.py`, `backend/app/research.py`, `frontend/src/api.ts`, `frontend/src/App.tsx` and progress UI | `backend/tests/test_jobs_v11.py`; cancel during long-running job |
| **P&L, drawdown, statistics or rejection analysis** — `backend/app/engine.py` and/or `backend/app/analysis.py` | `backend/app/storage.py`, `backend/app/models.py`, `frontend/src/components/Results.tsx`, `EquityDrawdown.tsx`, `AnalysisPanel.tsx`, `frontend/src/types.ts`, export/summary format, `backend/app/ai_prompt.py` when research assumptions change | `backend/tests/test_analysis.py`, engine regression tests; compare trade sums to equity and exported files |
| **Result saving, compression, manifests, pinning, retention, cache** — `backend/app/storage.py` | `backend/app/engine.py`, `backend/app/analysis.py`, `backend/app/main.py`, `frontend/src/components/StorageManager.tsx`, `Results.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `codex/ARCHITECTURE.md` | `backend/tests/test_v15_storage.py`; read legacy/plain/gz artifacts; ensure pinned runs/indexes survive |
| **Optimization, ablation or walk-forward** — `backend/app/research.py` | `backend/app/models.py`, `backend/app/engine.py`, `frontend/src/components/ResearchPanel.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `backend/app/ai_prompt.py` | `backend/tests/test_research_v5.py`; variants validate and do not leak holdout information |
| **Big Trend score/state, pivot/BOS, trend labels** — `backend/app/indicators.py`, `backend/app/rules.py`, `backend/app/trend_discovery.py` | `backend/app/engine.py`, `backend/app/models.py`, `backend/app/ai_prompt.py`, `frontend/src/components/BigTrendDetector.tsx`, `BigTrendAdvanced.tsx`, `BigTrendScoreEditor.tsx`, `TrendDiscoveryPanel.tsx`, `frontend/src/types.ts` | `backend/tests/test_big_trend_v10.py`, `test_big_trend_v12.py`, `test_market_structure_v6.py`; pivot confirmation and future-label isolation |
| **Chart data/markers/visual diagnostics** — `frontend/src/components/TradingChart.tsx` | `backend/app/main.py`, `backend/app/engine.py`, `backend/app/models.py`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/components/DecisionLog.tsx`, `Results.tsx`, `frontend/src/App.tsx` | Frontend build, timestamps and timezone, chart pan/zoom, marker-to-trade correspondence |
| **UI controls or user-facing feature** — affected `frontend/src/components/*.tsx` | `frontend/src/App.tsx`, `frontend/src/types.ts`, `frontend/src/defaults.ts`, `frontend/src/api.ts`, backend model/endpoint/engine if new behavior, `frontend/src/styles.css`, `backend/app/ai_prompt.py` if the feature affects strategy generation | Frontend build plus focused backend tests; control round-trip save/load and no silent default changes |
| **AI strategy generation instructions** — `backend/app/ai_prompt.py` | `backend/app/models.py` (authoritative JSON schema), `backend/app/indicators.py` (catalog), `backend/app/rules.py` (operators), `frontend/src/types.ts`, `codex/PROJECT.md`, `codex/DATA_AND_BACKTEST_RULES.md`, prompt guide if present | `backend/tests/test_ai_prompt.py`; generated JSON imports and validates; do not invent strategy fields or bump `schema_version` without a real migration |
| **Startup/config/environment/dependencies** — `backend/app/config.py`, `setup.ps1`, `start-dev.ps1`, package manifests | `README.md`, `codex/COMMANDS.md`, relevant `AGENTS.md`, `backend/app/main.py`, `frontend/vite.config.ts`, relevant scripts | Fresh-install/start smoke test; frontend build and backend compilation |
| **Version, behavior contract or project layout** | `README.md`, `codex/PROJECT.md`, `codex/ARCHITECTURE.md`, `codex/DATA_AND_BACKTEST_RULES.md`, `codex/CHANGE_CHECKLIST.md`, `backend/app/ai_prompt.py` when its claims change, and every affected `AGENTS.md` | Search for stale version claims, paths, commands, examples and unsupported features |

## Critical cross-cutting triggers

- **Backend contract changes** → inspect `frontend/src/types.ts`, `frontend/src/api.ts`, UI consumers, `models.py`, plus `ai_prompt.py` if the strategy schema or features changed.
- **Strategy behavior changes** → inspect strategy defaults/editors, prompt, regression tests, cache version, and migration/compatibility.
- **New visible feature** → implement its backend **and** expose it in the relevant UI; do not quietly introduce backend-only controls when the visual builder needs them.
- **New metric** → calculation, summary/export/analysis persistence, API typing, results UI, and correctness tests must agree on its units and meaning.
- **Data/fill assumption change** → preserve the `LOW_FIDELITY_SYNTHETIC_BBO` warning unless fidelity genuinely improves; SELL margin remains unmodeled unless explicitly implemented and validated.
- **Documentation-only changes** → no code edits required, but verify that documented paths/fields match the source.

## Required handoff format

Use this at the end of every coding task:

```text
Primary files changed:
Related files changed:
Related files inspected (no change needed):
Strategy JSON / API compatibility:
Cache and historical result implications:
Tests/builds run (with actual result):
Known limitations:
```

Do **not** claim "all related files updated" without inspecting the consumers and tests. If a necessary companion change is intentionally deferred, identify it explicitly as incomplete.
