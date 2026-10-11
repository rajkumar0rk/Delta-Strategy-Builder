# Change checklist for Codex

Before coding:

1. Read `AGENTS.md` plus the relevant backend/frontend nested AGENTS file.
2. Identify whether the task changes trading semantics, data semantics, persistence only, or UI only.
3. Check backward compatibility for saved strategy JSON and old result folders.

Before finishing:

1. Add or update focused tests.
2. Run the backend test suite for backend changes.
3. Run frontend build/type checks for frontend changes when dependencies are present.
4. Confirm no future information entered strategy decisions.
5. Confirm archive files were not modified unless the requested task is an explicit archive sync.
6. If engine behavior changed, consider cache-version bump.
7. If result persistence changed, confirm both legacy and V15 compressed artifacts remain readable.
8. Summarize exactly what changed and any limitations; do not claim unrun verification.
