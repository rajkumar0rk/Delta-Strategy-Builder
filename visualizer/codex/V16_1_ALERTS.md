# V16.1 — Independent strategy alerts

The strategy editor supports `BUY`, `SELL` or `ALERT` independently for
CALL and PUT. Selecting `ALERT` marks completed entry-rule transitions without
creating a position. Each direction has a separate editable message.

An additional **Strategy alerts** editor permits up to 30 independently named
alerts. Each alert has a stable ID, enabled toggle, **individual message** (up
to 500 characters), direction/marker placement, recursive rule tree,
`ON_ENTER` or `EVERY_BAR` mode, and cooldown in completed strategy candles.

Every triggered alert is its own marker containing its own text and message.
The chart includes an Alerts visibility toggle. Selecting a bar with multiple
events reveals event choices so each alert can be inspected separately.

- No broker order, capital, fees or P&L changes from alerts.
- Alert conditions are evaluated against completed strategy candles only.
- Preview and saved backtest use the same warm-up and rule evaluation.
- Alerts can fire while a simulated option position is open and during
  entry-session pauses; they are observation-only.
- Historical chart alerts are **not** real-time email/SMS/push notifications.
- The default empty alert list preserves existing strategy imports.
- `ANALYSIS` and `FULL_DEBUG` results persist alert markers; `COMPACT`
  also stores its alert markers separately from trade markers.
- No historical L1 quotes are needed for observation-only alerts.
- Strategy JSON remains `schema_version=15`; new alert fields are optional.
