# Codex context

For Codex work in this project, open the repository at:

```text
C:\projects\workspace\Delta-Strategy-Builder
```

When the task is about Strategy Lab, work under `visualizer/` and read `visualizer/AGENTS.md` first. The live strategy JSON contract is `visualizer/backend/app/models.py`, with a generated prompt from `visualizer/backend/app/ai_prompt.py`. See `visualizer/codex/STRATEGY_JSON_GENERATION_PROMPT.md` for the verified RSI/VWAP and underlying entry signal-candle stop semantics. Nested `backend/AGENTS.md` and `frontend/AGENTS.md` add directory-specific rules.

The files in this folder are reference context, not executable configuration. Keep them updated whenever architecture, data ownership, execution semantics, storage rules, or standard commands materially change.
