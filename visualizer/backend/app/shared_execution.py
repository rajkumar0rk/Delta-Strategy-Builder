"""Market-neutral, bounded helpers for futures and option underlying orders.

No exchange fills or option premium prices are modeled here. Consumers own their
market-specific quote, fee, contract and risk policies. No forward-bar reads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd


def clock_due(timestamp, time_hhmm: str | None, timezone: str) -> bool:
    """True on/after configured local time; consumers own quote availability."""
    if time_hhmm is None:
        return False
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        raise ValueError("Clock checks require timezone-aware candle times")
    local = stamp.tz_convert(ZoneInfo(timezone))
    return local.strftime("%H:%M") >= time_hhmm


def remaining_daily_risk(start_balance: float, realized_pnl: float,
                         daily_loss_percent: float | None) -> float | None:
    """Remaining room before a starting-day equity realized-loss threshold."""
    if daily_loss_percent is None:
        return None
    if not all(math.isfinite(float(v)) for v in
               (start_balance, realized_pnl, daily_loss_percent)):
        raise ValueError("Daily risk inputs must be finite")
    return max(0.0, float(start_balance) * daily_loss_percent / 100 + realized_pnl)


def pending_expired(signal_time, candle_close, base_minutes: int,
                    max_wait_bars: int, index_age: int) -> bool:
    """Both wall-clock and index age checked: data gaps cannot extend orders."""
    elapsed = (pd.Timestamp(candle_close) - pd.Timestamp(signal_time)).total_seconds()
    return index_age > max_wait_bars or elapsed > base_minutes * 60 * max_wait_bars


def stop_trigger_price(level: float, *, upward: bool, tick_size: float,
                       buffer_ticks: int = 1, buffer_points: float = 0) -> float:
    """Directionally tick-round beyond a frozen setup extreme."""
    if not all(math.isfinite(float(x)) for x in (level, tick_size, buffer_points)):
        raise ValueError("Stop trigger inputs must be finite")
    if tick_size <= 0 or buffer_ticks < 0 or buffer_points < 0:
        raise ValueError("Stop trigger tick/price buffers must be nonnegative")
    raw = level + buffer_points if upward else level - buffer_points
    ticks = max(1, buffer_ticks)
    units = raw / tick_size
    out = (math.floor(units + 1e-10) + ticks if upward
           else math.ceil(units - 1e-10) - ticks) * tick_size
    if out <= 0:
        raise ValueError("Nonpositive stop trigger")
    return round(out, 10)


def stop_trigger_on_bar(open_price: float, high: float, low: float, trigger: float,
                        *, upward: bool) -> float | None:
    """Wick-touch/gap-through proxy; no ordering within OHLC is claimed."""
    if not all(math.isfinite(float(x)) for x in (open_price, high, low, trigger)):
        return None
    if high < low or open_price <= 0:
        return None
    if upward:
        return max(open_price, trigger) if high >= trigger else None
    return min(open_price, trigger) if low <= trigger else None


@dataclass(slots=True)
class PendingUnderlyingStop:
    """One O(1)-sized pending order, contract selection delegated to consumer."""
    direction: str
    signal_time: pd.Timestamp
    setup_index: int
    trigger_price: float
    stop_price: float
    setup_level: float

    def expired(self, close, current_index: int, minutes: int, max_bars: int) -> bool:
        return pending_expired(self.signal_time, close, minutes, max_bars,
                               current_index - self.setup_index)

    def crossed(self, row) -> float | None:
        return stop_trigger_on_bar(row.open, row.high, row.low,
                                   self.trigger_price,
                                   upward=self.direction in ("LONG", "CALL"))
