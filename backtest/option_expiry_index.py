"""Optional indexed contract selection for legacy EMA/VWAP research.

Group by contract type and exact expiration so repeated signal lookups do
not scan every instrument. Keep original within-expiry row order to preserve
stable tie-breaking when strikes are equally distant or duplicate.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from typing import Sequence

from .data import OptionSpec

_DAY_NS = 24 * 60 * 60 * 1_000_000_000


class OptionExpiryIndex:
    """Immutable per-run index, reusable across signal configurations."""

    def __init__(self, specs: Sequence[OptionSpec]):
        buckets: dict[str, dict[int, list[OptionSpec]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for spec in specs:
            buckets[spec.option_type][spec.expiration_ns].append(spec)
        self._buckets = {
            kind: {expiry: tuple(rows) for expiry, rows in dates.items()}
            for kind, dates in buckets.items()
        }
        self._expiries = {
            kind: tuple(sorted(dates)) for kind, dates in self._buckets.items()
        }

    def select(
        self, signal_ns: int, direction: str, underlying: float, *,
        min_days_to_expiry: float = 1.0,
        min_days_to_expiry_inclusive: bool = True,
        max_days_to_expiry: float = 3.0,
    ) -> OptionSpec | None:
        if min_days_to_expiry < 0.0 or max_days_to_expiry < min_days_to_expiry:
            raise ValueError("invalid option expiry range")
        kind = "CE" if direction == "CALL" else "PE"
        expiries = self._expiries.get(kind, ())
        min_ns = signal_ns + int(min_days_to_expiry * _DAY_NS)
        max_ns = signal_ns + int(max_days_to_expiry * _DAY_NS)
        left = (
            bisect_left(expiries, min_ns)
            if min_days_to_expiry_inclusive
            else bisect_right(expiries, min_ns)
        )
        right = bisect_right(expiries, max_ns)
        for i in range(left, right):
            expiry = expiries[i]
            if expiry <= signal_ns:
                continue
            # The first expiry with an active contract wins; retain the
            # original row order for min(...) tie-breaking within that expiry.
            eligible = (
                item for item in self._buckets[kind][expiry]
                if item.activation_ns <= signal_ns < item.expiration_ns
            )
            selected = min(
                eligible,
                key=lambda item: (abs(item.strike - underlying), item.strike),
                default=None,
            )
            if selected is not None:
                return selected
        return None
