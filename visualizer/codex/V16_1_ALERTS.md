# Strategy-rule alerts (revised V16.1)

The existing strategy builder is the only editor for conditions. CALL/PUT
BUY/SELL actions remain distinct from per-direction entry/exit signal delivery:
ORDER_ONLY / ALERT_ONLY / BOTH.

ORDER_ONLY executes the normal simulated signal. ALERT_ONLY shows a historical
chart alert without executing that specific signal. For exits, protective risk
exits still apply. BOTH executes the order and shows an alert.

Each entry/exit signal has a separate editable message. Up to 30 additional
named warning alerts can reference an existing CALL/PUT entry/exit, shared or
directional NO TRADE rule, or an existing condition ID within one of these.
No duplicate conditions need to be created. Each warning has an independent
enabled switch, message, trigger mode, cooldown and marker placement.

Historical alerts are observation-only and do not require recorded L1.
Built-in entry alert rules reflect raw RuleGroup conditions: a real order
may still be blocked by risk, position, session, or liquidity.
Old V16.1 standalone alert conditions import as LEGACY_CUSTOM; new alerts
only reference already configured strategy rules. Old call_action=ALERT
migrates to BUY with ALERT_ONLY. Strategy schema_version stays 15.



Optional `reset_operand` references a non-chart-only indicator output. Changes
reset ON_ENTER state and cooldown; a missing/nonfinite identity suppresses the
alert. The DAY_LEVELS preset uses `daily.day_id` for daily rearming. Chart and
backtest share this behavior, including warm-up transition seeding. See
DAY_LEVEL_ALERTS.md for the eight historical warning/touch alerts.
