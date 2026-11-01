"""Normalize partial option exit legs into complete economic positions.

Keep raw trade legs for P&L/cash/fees and per-execution exports. Research win
rates, bootstrap, ablation and holdout must sample complete *positions*, not
correlated partial legs. Unresolved part-exited positions are excluded from
closed-position counts, but their realized cash remains in execution reports.
"""
from __future__ import annotations

from typing import Any


def _partial(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _pattern_record(value: Any) -> bool:
    # CSV round-trips turn Python None into the literal string "None".
    if isinstance(value,dict):
        return bool(value)
    return isinstance(value,str) and value.lstrip().startswith("{") and value.strip() not in ("{}", "{ }")


def closed_positions(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per completed position; standalone legacy trades remain unchanged."""
    grouped: dict[str, dict[str, Any]] = {}
    single: list[dict[str, Any]] = []
    for leg in legs:
        key = leg.get("position_group_id")
        if not key or not _pattern_record(leg.get("pattern_trade")):
            single.append(dict(leg))
            continue
        key = str(key)
        if key not in grouped:
            grouped[key] = {"parts": [], "complete": False}
        group = grouped[key]
        group["parts"].append(leg)
        group["complete"] |= not _partial(leg.get("partial_exit"))
    for key, item in grouped.items():
        if not item["complete"]:
            continue
        parts = sorted(item["parts"], key=lambda x: str(x.get("exit_time") or ""))
        last = dict(parts[-1])
        for name in ("net_pnl_usd", "gross_pnl_usd", "fees_usd", "entry_fee_usd",
                     "exit_fee_usd", "gst_usd", "base_fees_usd"):
            last[name] = sum(float(p.get(name) or 0) for p in parts)
        qty = sum(float(p.get("quantity") or 0) for p in parts)
        last["quantity"] = qty
        last["exit_legs"] = len(parts)
        last["partial_exit"] = False
        last["position_group_id"] = key
        last["entry_time"] = parts[0].get("entry_time")
        last["exit_time"] = parts[-1].get("exit_time")
        if qty > 0:
            last["return_percent"] = sum(
                float(p.get("return_percent") or 0)*float(p.get("quantity") or 0)
                for p in parts
            ) / qty
        last["holding_minutes"] = max(float(p.get("holding_minutes") or 0) for p in parts)
        single.append(last)
    return sorted(single, key=lambda r: (
        str(r.get("exit_time") or r.get("entry_time") or ""),
        str(r.get("position_group_id") or r.get("id") or ""),
    ))
