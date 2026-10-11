# BTC Strategy Lab — Codex instructions

Read `codex/PROJECT.md`, `codex/ARCHITECTURE.md`, `codex/DATA_AND_BACKTEST_RULES.md`, `codex/COMMANDS.md`, and **`codex/CHANGE_IMPACT_MATRIX.md`** before making non-trivial changes.

## Scope

This folder is the visual BTC options research/backtesting application inside the larger `Delta-Strategy-Builder` repository. The repository root is the parent of the current source app folder. In the user's current layout the source app folder is named `visualizer/`.

## Non-negotiable rules

- Preserve completed-candle / no-look-ahead semantics. Never make a signal actionable before all source candles and pivot confirmations required by that signal are complete.
- Do not fabricate missing market data, quotes, Greeks, implied volatility, margin, or liquidity.
- The default public-history archive is `../backtest/data/delta-history`; `catalog.json` is authoritative for active segments.
- Do not duplicate or move the public-history archive from Strategy Lab.
- Automatic history repair must go through the repository's `backtest.history_archive` module.
- Keep CALL/PUT direction mode, BUY/SELL option semantics, Delta fee + GST accounting, exclusive-position policy, cancellation checkpoints, and legacy strategy migration working.
- Research features may use future bars only for *labels/evaluation*. They must never feed future information into entry/exit decisions.
- Backtest storage should default in the UI to V15.1 `ANALYSIS`; large optimization/research inner runs should use `COMPACT` unless detailed traces are explicitly required.
- Never delete pinned result runs. Do not delete quote SQLite indexes as part of result cleanup.
- Prefer additive/migrating schema changes. Existing saved strategy JSON should continue to validate whenever practical.
- Avoid new dependencies unless the feature cannot be implemented cleanly with the existing stack.

## Mandatory companion-file rule

Before editing any file, consult `codex/CHANGE_IMPACT_MATRIX.md`, search for actual producers/consumers, and inspect the mapped companion files. Update affected backend, frontend, schema, AI prompt, tests, and documentation **in the same change**. Do not edit unrelated files just to satisfy the matrix. In the final response, list what was changed, what was inspected, and what remains unverified.

## Required verification

Backend changes:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q
```

Frontend changes, when dependencies are installed:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\frontend
npm run build
```

At minimum, run Python compilation for backend edits and TypeScript syntax/type checks for frontend edits. Do not claim tests/builds passed unless they were actually run.

## Change style

Keep logic deterministic and testable. Add focused tests for bug fixes and behavior changes. When touching result persistence, keep `summary.json` compact and put large diagnostics in dedicated compressed artifacts. When touching dataset selection, test boundary dates, overlapping segments, and missing files.

## V15.1 correctness invariants

- Higher-timeframe candle grouping is anchored to fixed UTC clock-close boundaries and MUST be independent of the requested backtest start time.
- Never infer timestamp units from `DatetimeIndex.astype("int64")`; Pandas 3 may expose microseconds. Use datetime-aware resampling/rounding.
- HTF indicators become available only after the full HTF candle closes; keep no-look-ahead alignment when forward-filling to the strategy timeframe.
- Contract `min_quantity` and `size_increment` are always enforced. `risk.enforce_trade_budget_strict` controls only whether a valid minimum/fixed quantity may exceed `budget_usd`.
- Result directories must be created exclusively with collision-proof IDs; never use `exist_ok=True` for a new run folder.
- Preserve the LOW_FIDELITY_SYNTHETIC_BBO warning in results and AI/Codex context.

## V15.2 + V16 change invariants

Use codex/CHANGE_IMPACT_MATRIX.md for all edits. Keep request-level warm-up separate from StrategyConfig. Chart and backtest share no-lookahead completed-HTF indicators; do not trade pre-range. Preserve closed-trade versus quote-observed MTM drawdown. Do not close open positions against stale final quotes. Mark low-fidelity results RESEARCH_ONLY; V16 execution stress is **post-trade analysis**, not a new fill simulator. Synchronize AI prompt, backend tests, UI/API contracts and docs with relevant changes.
