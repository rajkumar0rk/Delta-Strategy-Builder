"""Stateful first EMA touch after a fully confirmed higher-timeframe Supertrend flip.

The caller provides completed 5m bars with causally aligned 1h Supertrend
and EMA20 columns. The first touch is a 5m CLOSE signal: fills happen at
the NEXT 5m open; this is deliberately not a 1-minute/tick execution model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class SupertrendEMATouchCycle:
    supertrend_id: str
    ema_id: str
    direction: str | None = None
    armed_at: pd.Timestamp | None = None
    consumed: bool = False

    def observe(self, ts: pd.Timestamp, bar) -> dict | None:
        """Consume the earliest completed post-flip 5m EMA touch, once per cycle.

        Values are forward filled from completed 1h bars. Flip flags can
        therefore be repeated on several 5m bars; recognize them ONLY at
        the actual UTC 1h closing timestamp, never on a repeated flag.
        """
        if ts.minute == 0 and ts.second == 0:
            bullish = bar.get(f"{self.supertrend_id}.bullish_flip")
            bearish = bar.get(f"{self.supertrend_id}.bearish_flip")
            if _flag(bullish) or _flag(bearish):
                self.direction = "LONG" if _flag(bullish) else "SHORT"
                self.armed_at = ts
                self.consumed = False
            else:
                raw = _number(bar.get(f"{self.supertrend_id}.direction"))
                if self.direction and raw is not None and raw != (1 if self.direction == "LONG" else -1):
                    self.direction = None
                    self.armed_at = None
                    self.consumed = True
        if self.armed_at is None or ts <= self.armed_at or self.consumed:
            return None
        ema = _number(bar.get(self.ema_id))
        ref = _number(bar.get(f"{self.supertrend_id}.line"))
        low = _number(bar.get("low"))
        high = _number(bar.get("high"))
        if ema is None or ref is None or low is None or high is None:
            return None
        if low <= ema <= high:
            self.consumed = True
            return {
                "direction": self.direction,
                "signal_time": ts.isoformat(),
                "ema_touch_level": ema,
                "supertrend_reference_line": ref,
            }
        return None

    def opposite_flip_at_close(self, ts: pd.Timestamp, bar, direction: str) -> bool:
        """Only a real completed 1h opposite flip, never a line touch."""
        if ts.minute != 0 or ts.second != 0:
            return False
        output = "bearish_flip" if direction == "LONG" else "bullish_flip"
        return _flag(bar.get(f"{self.supertrend_id}.{output}"))


def _number(value) -> float | None:
    try:
        num = float(value)
        return num if math.isfinite(num) else None
    except (ValueError, TypeError):
        return None


def _flag(value) -> bool:
    num = _number(value)
    return num is not None and num > 0.5
