"""Stateful floating-point rolling mean with Pandas' compensated sum behavior.

Pandas rolling(...).mean() retains Kahan addition/removal compensation and
consecutive-equal-value state across the entire source Series. Recreating its
last three numbers inside each CSV chunk can change comparisons such as
Stoch RSI K < D by just one or two floating-point ULPs, even though numeric
tolerance tests pass. Keeping the rolling accumulator across chunks preserves
the original Pandas strict-comparison semantics without retaining all bars.

This is specific to fixed-width windows with min_periods=window, matching
the two 3-bar Stoch RSI smoothing operations used by the legacy research
engine. Validate against the installed Pandas rolling implementation.
"""
from __future__ import annotations

from collections import deque
import math


class CompensatedRollingMean:
    """Retain Pandas rolling-mean state between input chunks."""

    def __init__(self, window: int):
        if type(window) is not int or window < 1:
            raise ValueError("rolling window must be a positive integer")
        self.window = window
        self._history: deque[float] = deque()
        self._sum = 0.0
        self._add_compensation = 0.0
        self._remove_compensation = 0.0
        self._observations = 0
        self._negative_count = 0
        self._previous = math.nan
        self._consecutive_equal = 0
        self._started = False

    def update(self, number: float) -> float:
        value = float(number)
        if not self._started:
            self._previous = value
            self._started = True

        if len(self._history) == self.window:
            expired = self._history.popleft()
            if expired == expired:  # Pandas ignores NaNs for rolling means.
                self._observations -= 1
                adjustment = -expired - self._remove_compensation
                updated = self._sum + adjustment
                self._remove_compensation = updated - self._sum - adjustment
                self._sum = updated
                if math.copysign(1.0, expired) < 0:
                    self._negative_count -= 1

        self._history.append(value)
        if value == value:
            self._observations += 1
            adjustment = value - self._add_compensation
            updated = self._sum + adjustment
            self._add_compensation = updated - self._sum - adjustment
            self._sum = updated
            if math.copysign(1.0, value) < 0:
                self._negative_count += 1
            if value == self._previous:
                self._consecutive_equal += 1
            else:
                self._consecutive_equal = 1
            self._previous = value

        if self._observations < self.window:
            return math.nan
        result = self._sum / float(self._observations)
        if self._consecutive_equal >= self._observations:
            return self._previous
        if self._negative_count == 0 and result < 0:
            return 0.0
        if self._negative_count == self._observations and result > 0:
            return 0.0
        return result
