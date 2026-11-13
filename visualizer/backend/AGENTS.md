# Backend agent instructions

These rules extend `../AGENTS.md` for `backend/`.

- FastAPI entrypoint: `app/main.py`.
- Pydantic contracts and migrations: `app/models.py`.
- Main deterministic backtest loop: `app/engine.py`.
- Indicator registry + implementations: `app/indicators.py`.
- Rule operators/evaluation: `app/rules.py`.
- Dataset/catalog/quote-index logic: `app/data_store.py`.
- Archive download orchestration: `app/archive_sync.py`; do not reimplement Delta download logic here.
- Result persistence/retention: `app/storage.py`.
- Research sweeps/walk-forward: `app/research.py`.
- Historical BIG-vs-fake labels: `app/trend_discovery.py`.

When editing `risk.stop_loss.mode=UNDERLYING_SIGNAL_CANDLE`, preserve the frozen completed signal-candle price anchor, monotonic stop-candle scanning, chronological quote execution, unresolved stop exposure reporting, and directional BUY CALL/SELL PUT vs BUY PUT/SELL CALL rules. Update `visualizer/codex/STRATEGY_JSON_GENERATION_PROMPT.md` and focused backend tests together.

Use UTC internally unless a feature explicitly uses strategy session timezone. Option entry/exit execution must continue to use executable bid/ask sides, not candle midpoint. SELL-option margin remains unmodeled unless real venue/account data becomes available.

For large loops, keep cooperative `progress(...)` checkpoints so the Stop button can cancel safely.


V15.1 correctness rules:
- Higher-timeframe aggregation must use fixed UTC candle-close boundaries and datetime-aware Pandas operations; never assume datetime integer units are nanoseconds.
- Add/keep regression coverage using a microsecond (`datetime64[us]`) index and different requested From times.
- Always validate option `min_quantity` and `size_increment`. `enforce_trade_budget_strict` only controls budget rejection, not exchange validity.
- New result folders require collision-proof IDs and exclusive creation.
