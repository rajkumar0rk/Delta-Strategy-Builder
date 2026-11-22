"""Stateful first EMA touch after a fully confirmed higher-timeframe Supertrend flip.

The caller provides completed 5m bars with causally aligned 1h Supertrend
and EMA20 columns. The first touch is a 5m CLOSE signal: fills happen at
the NEXT 5m open; this is deliberately not a 1-minute/tick execution model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SupertrendEMATouchCycle:
    supertrend_id: str
    ema_id: str
    direction: str | None = None
    armed_at: pd.Timestamp | None = None
    consumed: bool = False
    entry_mode: str = "FIRST_TOUCH"
    breakout_lookback_bars: int = 12
    require_ema_slope: bool = True
    swing_stop_lookback_bars: int = 12
    recent_bars: list[tuple[float, float]] = field(default_factory=list)
    last_confirmed_ema: float | None = None
    confirmed_ema_slope: float | None = None

    def _breakout_or_rejection(self, ts: pd.Timestamp, bar) -> dict | None:
        """One completed 5m breakout/rejection signal per confirmed 1h flip.

        The breakout comparison uses ONLY earlier, completed 5m candles.
        The slope compares the TWO last confirmed hourly EMA20 values.
        Historical 5m highs/lows are recorded after signal evaluation.
        """
        low=_number(bar.get("low"))
        high=_number(bar.get("high"))
        opened=_number(bar.get("open"))
        closed=_number(bar.get("close"))
        ema=_number(bar.get(self.ema_id))
        history=self.recent_bars
        limit=max(self.breakout_lookback_bars,self.swing_stop_lookback_bars)
        try:
            if ts.minute==0 and ts.second==0:
                if ema is not None:
                    if self.last_confirmed_ema is not None:
                        self.confirmed_ema_slope=ema-self.last_confirmed_ema
                    self.last_confirmed_ema=ema
                up=_flag(bar.get(f"{self.supertrend_id}.bullish_flip"))
                down=_flag(bar.get(f"{self.supertrend_id}.bearish_flip"))
                if up or down:
                    self.direction="LONG" if up else "SHORT"
                    self.armed_at=ts
                    self.consumed=False
                else:
                    raw=_number(bar.get(f"{self.supertrend_id}.direction"))
                    if self.direction is not None and raw is not None and raw!=(
                        1 if self.direction=="LONG" else -1
                    ):
                        self.direction=None
                        self.armed_at=None
                        self.consumed=True
            if (self.direction is None or self.armed_at is None or ts<=self.armed_at
                    or self.consumed or None in (low,high,opened,closed,ema)):
                return None
            sign=1 if self.direction=="LONG" else -1
            if sign*(closed-ema)<=0:
                return None
            if self.require_ema_slope and (
                self.confirmed_ema_slope is None or
                sign*self.confirmed_ema_slope<=0
            ):
                return None
            breakout=False
            if len(history)>=self.breakout_lookback_bars:
                prior=history[-self.breakout_lookback_bars:]
                level=(max(x[1] for x in prior) if sign==1
                       else min(x[0] for x in prior))
                breakout=(closed>level if sign==1 else closed<level)
            rejection=(self.entry_mode=="BREAKOUT_OR_REJECTION" and
                       low<=ema<=high and sign*(closed-opened)>0)
            if not breakout and not rejection:
                return None
            if len(history)<self.swing_stop_lookback_bars:
                return None
            reference=history[-self.swing_stop_lookback_bars:]
            # Include the signal candle's own wick in the protected swing.
            swing_stop=(min([low]+[x[0] for x in reference]) if sign==1
                        else max([high]+[x[1] for x in reference]))
            self.consumed=True  # never reenter in this Supertrend cycle
            return {
                "direction":self.direction,
                "signal_time":ts.isoformat(),
                "entry_trigger":"BREAKOUT" if breakout else "EMA_REJECTION",
                "setup_stop_price":swing_stop,
                "ema_touch_level":ema,
                "supertrend_reference_line":_number(bar.get(f"{self.supertrend_id}.line")),
            }
        finally:
            if low is not None and high is not None:
                history.append((low,high))
                if len(history)>limit:
                    del history[:-limit]

    def observe(self, ts: pd.Timestamp, bar) -> dict | None:
        if self.entry_mode!="FIRST_TOUCH":
            return self._breakout_or_rejection(ts,bar)
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
