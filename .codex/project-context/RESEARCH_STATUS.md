# Research Status

No strategy in this repository is proven production-ready.

Key conclusions to retain:

- Several positive aggregate results are highly sensitive to an exceptional
  August 2026 option move. Always calculate results without the largest winner.
- Full-BBO execution is an optimistic bound.
- Size-aware runs based on synthetic one-minute volume are stress tests, not a
  measurement of historical order-book capacity.
- A harsh zero-value policy for unfilled exit residuals can dominate results.
- Small session-specific advantages have limited samples and selection bias.
- Adding filters can remove good trades as well as losses; rejection counts and
  removed-winner/removed-loser P&L are required to judge a filter.

For every experiment compare net P&L after fees, profit factor, maximum
drawdown, average win/loss, largest win, P&L per trade, profitable months,
CALL/PUT P&L, trade count, and outlier-free P&L.
