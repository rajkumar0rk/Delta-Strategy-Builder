"""Opt-in sequential core indicators over bounded historical CSV input batches.

EMA, Wilder RSI/ATR and MACD state persists across chunk boundaries. The
resulting core DataFrame still contains all selected candles because the legacy
signal engine and its Pandas rolling/session features need full history.
Never silently re-order unsorted input: fail closed rather than alter signals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class CoreIndicatorState:
    count: int = 0
    previous_close: float | None = None
    ema_values: dict[int, float] = field(default_factory=dict)
    macd_signal: float | None = None
    gain_sum: float = 0.0
    loss_sum: float = 0.0
    average_gain: float | None = None
    average_loss: float | None = None
    atr_seed: float = 0.0
    atr_value: float | None = None

    def _ema(self, price: float, period: int) -> float:
        prior = self.ema_values.get(period)
        result = (
            price if prior is None
            else (2.0 / (period + 1.0)) * price
            + (1.0 - 2.0 / (period + 1.0)) * prior
        )
        self.ema_values[period] = result
        return result

    def update(self, high: float, low: float, close: float) -> tuple[float, ...]:
        """Return EMA9, EMA20, EMA50, RSI14, ATR14, MACD and MACD signal."""
        i = self.count
        ema9 = self._ema(close, 9)
        ema20 = self._ema(close, 20)
        ema50 = self._ema(close, 50)
        fast = self._ema(close, 12)
        slow = self._ema(close, 26)
        macd = fast - slow
        if self.macd_signal is None:
            self.macd_signal = macd
        else:
            alpha = 2.0 / 10.0
            self.macd_signal = alpha * macd + (1.0 - alpha) * self.macd_signal

        rsi = math.nan
        if self.previous_close is not None:
            change = close - self.previous_close
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            if i <= 14:
                self.gain_sum += gain
                self.loss_sum += loss
                if i == 14:
                    self.average_gain = self.gain_sum / 14
                    self.average_loss = self.loss_sum / 14
            else:
                assert self.average_gain is not None and self.average_loss is not None
                self.average_gain = (self.average_gain * 13 + gain) / 14
                self.average_loss = (self.average_loss * 13 + loss) / 14
        if self.average_gain is not None and self.average_loss is not None:
            if self.average_loss == 0.0:
                rsi = 100.0 if self.average_gain > 0.0 else 50.0
            else:
                rsi = 100.0 - 100.0 / (1.0 + self.average_gain / self.average_loss)

        tr = (
            high - low
            if self.previous_close is None
            else max(high - low, abs(high - self.previous_close),
                     abs(low - self.previous_close))
        )
        atr = math.nan
        if i < 14:
            self.atr_seed += tr
            if i == 13:
                self.atr_value = self.atr_seed / 14
        else:
            assert self.atr_value is not None
            self.atr_value = (self.atr_value * 13 + tr) / 14
        if self.atr_value is not None:
            atr = self.atr_value

        self.previous_close = close
        self.count += 1
        return ema9, ema20, ema50, rsi, atr, macd, self.macd_signal


def iter_streamed_core_chunks(path: Path, chunk_rows: int):
    """Yield core-indicator CSV batches without accumulating them."""
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ValueError("indicator_chunk_rows must be a positive integer")
    state = CoreIndicatorState()
    last_timestamp: pd.Timestamp | None = None
    for chunk in pd.read_csv(path, parse_dates=["timestamp"], chunksize=chunk_rows):
        chunk = chunk.set_index("timestamp")
        if not isinstance(chunk.index, pd.DatetimeIndex) or chunk.index.tz is None:
            raise ValueError("STREAMED_INDICATOR_TIMESTAMPS_REQUIRE_TIMEZONE")
        # A full-frame sort changes the order of unclean archives; streaming
        # cannot safely do so without an external merge-sort.
        if not chunk.index.is_monotonic_increasing or (
            last_timestamp is not None and len(chunk)
            and chunk.index[0] < last_timestamp
        ):
            raise ValueError("STREAMED_INDICATOR_TIMESTAMPS_OUT_OF_ORDER")
        if len(chunk):
            last_timestamp = chunk.index[-1]
        for column in ("open", "high", "low", "close", "volume"):
            chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
        chunk = chunk.dropna(subset=["open", "high", "low", "close", "volume"])
        if chunk.empty:
            continue
        outputs = [
            state.update(float(high), float(low), float(close))
            for high, low, close in zip(
                chunk["high"], chunk["low"], chunk["close"]
            )
        ]
        for pos, name in enumerate(
            ("ema9", "ema20", "ema50", "rsi14", "atr14", "macd", "macd_signal")
        ):
            chunk[name] = [row[pos] for row in outputs]
        yield chunk


def streamed_core_frame(path: Path, chunk_rows: int) -> pd.DataFrame:
    """Compatibility adapter: intentionally materializes all yielded chunks."""
    parts = list(iter_streamed_core_chunks(path, chunk_rows))
    if not parts:
        # Keep the familiar schema so a downstream no-data error is descriptive.
        empty = pd.read_csv(path, nrows=0, parse_dates=["timestamp"]).set_index("timestamp")
        return empty
    return pd.concat(parts, axis=0)
