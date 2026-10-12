"""Historical alerts referencing the EXISTING strategy rule trees.

Alert evaluation is read-only: no option lookup, orders, capital or positions.
"""
from __future__ import annotations

import pandas as pd

from .models import AlertRule, ALERT_SOURCE_FIELDS
from .rules import evaluate_condition, evaluate_group, find_condition

MAX_MARKERS = 100_000


def configured_alerts(strategy) -> list[AlertRule]:
    result = list(strategy.alerts)
    for side in ("call", "put"):
        enabled = strategy.direction_mode in {side.upper(), "BOTH"}
        if not enabled:
            continue
        for event, name, message in (
            ("entry", f"{side.upper()} entry signal", getattr(strategy, f"{side}_alert_message")),
            ("exit", f"{side.upper()} exit signal", getattr(strategy, f"{side}_exit_alert_message")),
        ):
            key = f"{side}_{event}_signal_mode" if event == "exit" else f"{side}_signal_mode"
            if getattr(strategy, key) in {"ALERT_ONLY", "BOTH"}:
                result.append(AlertRule(
                    id=f"builtin-{side}-{event}", name=name, message=message,
                    direction=side.upper(), source=f"{side.upper()}_{event.upper()}",
                ))
    return result


def alert_markers(frame: pd.DataFrame, strategy, start: str, end: str) -> list[dict]:
    """Alert transitions/cooldowns are seeded by warm-up, never emitted before From.

    Individual alerts may reference a full existing RuleGroup or one condition
    inside it. Existing V16.1 custom-condition alerts are supported for import.
    """
    entries = []
    for alert in configured_alerts(strategy):
        if not alert.enabled:
            continue
        group = (alert.conditions if alert.source == "LEGACY_CUSTOM"
                 else getattr(strategy, ALERT_SOURCE_FIELDS[alert.source]))
        if not group.configured():
            continue
        condition = find_condition(group, alert.condition_id) if alert.condition_id else None
        entries.append((alert, group, condition))

    if not entries or frame.empty:
        return []

    cutoff = pd.Timestamp(start)
    until = pd.Timestamp(end)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tz is None else cutoff.tz_convert("UTC")
    until = until.tz_localize("UTC") if until.tz is None else until.tz_convert("UTC")
    prev = {a.id: False for a, _, _ in entries}
    last_trigger: dict[str, int] = {}
    result: list[dict] = []
    for i, (ts, _) in enumerate(frame.iterrows()):
        if ts >= until:
            break
        for alert, group, condition in entries:
            evaluated = (evaluate_condition(frame, i, condition) if condition is not None
                         else evaluate_group(frame, i, group))
            passed = bool(evaluated["passed"])
            entered = passed and not prev[alert.id]
            prev[alert.id] = passed
            if not passed or (alert.trigger_mode == "ON_ENTER" and not entered):
                continue
            previous = last_trigger.get(alert.id)
            if previous is not None and i - previous <= alert.cooldown_bars:
                continue
            last_trigger[alert.id] = i
            if ts < cutoff:
                continue
            result.append({
                "id": f"alert-{alert.id}-{int(ts.timestamp())}",
                "time": int(ts.timestamp()),
                "timestamp": ts.isoformat(),
                "kind": "alert",
                "direction": alert.direction,
                "text": f"ALERT: {alert.name}",
                "pnl_usd": None,
                "details": {
                    "title": f"Alert triggered: {alert.name}",
                    "message": alert.message.strip() or f"{alert.name} conditions triggered",
                    "reason": "ALERT_CONDITIONS_MET",
                    "alert_id": alert.id,
                    "alert_name": alert.name,
                    "source": alert.source,
                    "condition_id": alert.condition_id,
                    "trigger_mode": alert.trigger_mode,
                    "cooldown_bars": alert.cooldown_bars,
                },
            })
            if len(result) > MAX_MARKERS:
                raise ValueError("More than 100,000 alert events would be generated. "
                                 "Use ON_ENTER or increase cooldown to limit chart history.")
    return result
