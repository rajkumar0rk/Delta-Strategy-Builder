"""Low-impact accounting of already materialized JSON-like backtest reports.

Provides a directional estimate of live Python-owned report objects, not
NumPy allocations, process heap fragmentation, or peak RSS. Shared objects
are counted once within each measured root; partition totals must not be
added together because roots may share references.
"""
from __future__ import annotations

import sys
from typing import Any


def deep_json_tree_bytes(root: Any) -> int:
    """Approximate Python bytes retained by a report mapping/list tree.

    Accept only the containers and scalar types produced by the legacy JSON
    report. Unknown objects contribute their shallow size but are not walked.
    The identity set handles repeated references and accidental cycles.
    """
    seen: set[int] = set()
    pending: list[Any] = [root]
    total = 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            pending.extend(item)
    return total


def report_retained_sizes(report: dict[str, Any]) -> dict[str, Any]:
    """Return standalone per-field estimates and whole-report unique total."""
    return {
        "total_unique_python_bytes": deep_json_tree_bytes(report),
        "fields": {
            key: deep_json_tree_bytes(value)
            for key, value in report.items()
        },
        "note": (
            "Field footprints are separately counted and may overlap; do not "
            "sum them. These are Python object estimates, not process RSS or "
            "all NumPy/Pandas native memory."
        ),
    }
