"""Independent futures entry-lifecycle state replay for chart/backtest parity.

Consumes completed-candle raw trigger booleans from chart preview plus actual
position intervals. Does not call engine's _update_cycle/_cycle_eligible helpers.
This verifies lifecycle *transitions and filled-entry provenance*, NOT the
independent generation of trade/exit decisions or Delta exchange fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import StrategyConfig


def _epoch(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@dataclass
class Cycle:
    started_at: int | None = None
    entries: int = 0
    last_fill_index: int | None = None
    expired: bool = False


def independently_replay_lifecycles(result: dict, source: list[dict], timeframe_minutes: int) -> dict:
    """Compare state reconstructed from independent trigger timeline to fills.

    Source must include every warm-up candle in chronological order. Trade
    timestamps are the entry bar OPEN (previous candle close) in this engine.
    """
    failures: list[str] = []
    if not source:
        return {"checked": 0, "failures": ["Missing historical lifecycle trigger timeline"]}
    strategy = StrategyConfig.model_validate(result["strategy"])
    step = timeframe_minutes * 60
    selected = {
        "CALL": strategy.call_entry_lifecycles or [strategy.call_entry_behavior],
        "PUT": strategy.put_entry_lifecycles or [strategy.put_entry_behavior],
    }
    selected = {side: {b.id: b for b in behaviors if b.enabled}\n                if strategy.direction_mode in (side, "BOTH") and\n                   (strategy.call_signal_mode if side == "CALL" else strategy.put_signal_mode) != "ALERT_ONLY"\n                else {} for side, behaviors in selected.items()}
    cycles = {side: {ident: Cycle() for ident in group} for side, group in selected.items()}
    trades = list(result.get("trades") or [])
    if result.get("unresolved_position"):
        trades.append(result["unresolved_position"])
    events = {}
    for position in trades:
        entry = _epoch(position["entry_time"])
        events.setdefault(entry, []).append(position)
    index_by_time = {}
    checked = 0

    def active_at_close(timestamp: int) -> str | None:
        active = []
        for trade in trades:
            start = _epoch(trade["entry_time"])
            if start >= timestamp:
                continue
            if not trade.get("exit_time"):
                active.append(trade["direction"])
                continue
            end = _epoch(trade["exit_time"])
            if end > timestamp or (end == timestamp and trade.get("exit_fill_timing") == "OPEN"):
                active.append(trade["direction"])
        if len(active) > 1:
            failures.append(f"Overlapping positions at completed candle {timestamp}")
        return active[0] if active else None

    for i, row in enumerate(source):
        timestamp = _epoch(row["time"])
        if timestamp in index_by_time:
            failures.append(f"Duplicate lifecycle trigger candle {timestamp}")
            continue
        index_by_time[timestamp] = i
        at_open = timestamp - step
        # Consume accepted fills at this candle's OPEN, before updating state
        # for its completed candle, matching the futures order lifecycle.
        for trade in events.get(at_open, []):
            side = "CALL" if trade["direction"] == "LONG" else "PUT"
            ident = trade.get("entry_lifecycle_id")
            if not ident or ident not in cycles[side]:
                failures.append(f"Missing or unrecognized lifecycle ID at entry {at_open}")
                continue
            cycle = cycles[side][ident]
            if cycle.started_at is None:
                failures.append(f"Entry consumed without an active lifecycle at {at_open}")
            cycle.entries += 1
            cycle.last_fill_index = i
        exposure = active_at_close(timestamp)
        active_sides = ("CALL", "PUT") if exposure is None else (("CALL",) if exposure == "LONG" else ("PUT",))
        for side in active_sides:
            triggers = row.get(side.lower(), {})
            for ident, behavior in selected[side].items():
                state = cycles[side][ident]
                if ident not in triggers:
                    failures.append(f"Missing raw {side} trigger for lifecycle {ident} at {timestamp}")
                    continue
                if not bool(triggers[ident]):
                    cycles[side][ident] = Cycle()
                    continue
                if state.started_at is None:
                    state.started_at = i
                    state.entries = 0
                    state.last_fill_index = None
                    state.expired = False
                age = i - state.started_at
                if behavior.max_wait_bars is not None and age > behavior.max_wait_bars:
                    state.expired = True
                eligible = (
                    not state.expired
                    and age >= behavior.delay_bars
                    and state.entries < behavior.max_entries_per_activation
                    and (state.last_fill_index is None or
                         i - state.last_fill_index > behavior.cooldown_bars)
                )
                for trade in events.get(timestamp, []):
                    if (trade["direction"] == ("LONG" if side == "CALL" else "SHORT")
                            and trade.get("entry_lifecycle_id") == ident):
                        # Entry at timestamp is the NEXT bar's open, based on
                        # the completed signal candle timestamp here.
                        checked += 1
                        values = {
                            "entry_lifecycle_age_bars": age,
                            "entry_lifecycle_delay_bars": behavior.delay_bars,
                            "entry_lifecycle_entries_before": state.entries,
                            "entry_lifecycle_max_entries": behavior.max_entries_per_activation,
                            "entry_lifecycle_expired": state.expired,
                            "entry_lifecycle_eligible": eligible,
                        }
                        for field, expected in values.items():
                            if field not in trade or trade[field] != expected:
                                failures.append(f"{field} differs from independent lifecycle replay at {timestamp} {ident}")
    for trade in trades:
        entry = _epoch(trade["entry_time"])
        if entry not in index_by_time:
            failures.append(f"No completed trigger candle for executed entry at {entry}")
    if checked != len(trades):
        failures.append(f"Independently checked {checked} of {len(trades)} futures entries")
    return {"checked": checked, "total_entries": len(trades),
            "failures": list(dict.fromkeys(failures))[:30],
            "source_bars": len(source)}
