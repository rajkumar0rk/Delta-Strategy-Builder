"""Independent, historical, completed-candle chart alerts.

Alert events never select options, execute orders or change strategy capital.
"""
from __future__ import annotations

import pandas as pd

from .models import AlertRule
from .rules import evaluate_group

MAX_MARKERS = 100_000


def configured_alerts(strategy) -> list[AlertRule]:
    result = list(strategy.alerts)
    if strategy.direction_mode in {"CALL", "BOTH"} and strategy.call_action == "ALERT":
        result.append(AlertRule(id="action-call", name="CALL entry signal",
                                message=strategy.call_alert_message, direction="CALL",
                                conditions=strategy.call_entry))
    if strategy.direction_mode in {"PUT", "BOTH"} and strategy.put_action == "ALERT":
        result.append(AlertRule(id="action-put", name="PUT entry signal",
                                message=strategy.put_alert_message, direction="PUT",
                                conditions=strategy.put_entry))
    return result


def alert_markers(frame: pd.DataFrame, strategy, start: str, end: str) -> list[dict]:
    """Evaluate independent named alerts before clipping warm-up candles.

    ON_ENTER fires on a false-to-true transition. EVERY_BAR fires on all passing
    completed bars (subject to cooldown). No options/L1 history is required.
    """
    items = [a for a in configured_alerts(strategy) if a.enabled and a.conditions.configured()]
    if not items or frame.empty:
        return []
    cutoff = pd.Timestamp(start)
    until = pd.Timestamp(end)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tz is None else cutoff.tz_convert("UTC")
    until = until.tz_localize("UTC") if until.tz is None else until.tz_convert("UTC")
    prev = {a.id: False for a in items}
    last_trigger: dict[str, int] = {}
    result: list[dict] = []
    for i, (ts, _) in enumerate(frame.iterrows()):
        if ts >= until:
            break
        for alert in items:
            passed = bool(evaluate_group(frame, i, alert.conditions)["passed"])
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
                    "trigger_mode": alert.trigger_mode,
                    "cooldown_bars": alert.cooldown_bars,
                },
            })
            if len(result) > MAX_MARKERS:
                raise ValueError("More than 100,000 alert events would be generated. "
                                 "Use ON_ENTER or increase cooldown to limit chart history.")
    return result
