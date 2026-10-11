# Frontend agent instructions

These rules extend `../AGENTS.md` for `frontend/`.

- React + TypeScript + Vite.
- `src/App.tsx` owns top-level workflow/state.
- `src/api.ts` is the backend API boundary.
- `src/types.ts` mirrors backend response/config contracts.
- `src/defaults.ts` defines new-strategy defaults only; do not use defaults to silently rewrite loaded strategies.
- Keep chart interaction TradingView-like and preserve manual pan/zoom/pane state where possible.
- Strategy builder controls must expose engine capabilities rather than hiding backend-only features.
- Long operations need visible progress and a Stop action when the backend job supports cancellation.
- Destructive storage actions require an explicit user confirmation. Pinned runs must be visibly distinguishable.

Avoid adding frontend packages for small UI changes. Prefer existing CSS and browser APIs.
