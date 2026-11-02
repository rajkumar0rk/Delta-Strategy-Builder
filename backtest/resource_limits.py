"""Opt-in fail-closed admission controls for original legacy EMA/VWAP research.

These limits prevent unbounded *admitted* collections; they do not imply a
hard process RSS cap, change market data, or silently drop research records.
Unset (None) limits preserve the previous behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class LegacyResourceLimits:
    max_underlying_bars: int | None = None
    max_option_instruments: int | None = None
    max_scenarios: int | None = None
    max_signal_events: int | None = None
    max_decision_events: int | None = None
    max_execution_attempts: int | None = None
    max_trades: int | None = None

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{item.name} must be a positive integer or None")


class DecisionEventBudget:
    """Shared cap for emitted signal and execution diagnostics.

    The final report may repeat a config's signal diagnostics for each scenario;
    this budget counts source records once, not those report copies.
    """

    def __init__(self, limit: int):
        if type(limit) is not int or limit < 1:
            raise ValueError("max_decision_events must be positive")
        self.limit = limit
        self.count = 0

    def charge(self) -> None:
        if self.count >= self.limit:
            raise ValueError("LEGACY_DECISION_EVENT_LIMIT_EXCEEDED")
        self.count += 1


class LimitedDecisionEvents(list[dict[str, Any]]):
    def __init__(self, budget: DecisionEventBudget):
        super().__init__()
        self._budget = budget

    def append(self, record: dict[str, Any]) -> None:
        self._budget.charge()
        super().append(record)
