# Historical option quote timestamp repair

First-quote and quote-range lookups now preserve inclusive UTC boundaries when
old SQLite indexes mix integral and fractional-second ISO timestamps. Indexed
second-prefix bounds limit the candidate rows; exact datetime comparison and
chronological ordering determine eligibility. No market data or existing quote
index is deleted, rewritten or rebuilt by this change.

Options backtest cache identity is 180. Previously saved results remain intact;
a fresh run uses the corrected lookup. This does not establish that any previous
minute-aligned synthetic-quote result was affected. Indicator, strategy, fee,
session and 15% stop settings are unchanged. Backend/schema, AI prompt, archive,
analysis and frontend consumers were reviewed; their contracts do not change.

Regression coverage is in backend/tests/test_quote_timestamp_precision.py and
the existing correctness/archive/session tests. Large archive backtests and
real historical order-book execution are separate verification work.
