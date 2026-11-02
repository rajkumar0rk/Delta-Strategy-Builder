"""Optional, lossless positional windows on completed historical candles.

Only use binary-search positions for a sorted DatetimeIndex. Unsorted and
non-datetime frames fall back to the historical Pandas mask/slice operations,
so no implicit reordering or missing-candle imputation occurs.
"""
from __future__ import annotations

import math

import pandas as pd


def completed_window(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """All rows through cutoff inclusive, retaining duplicate candle timestamps."""
    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.is_monotonic_increasing:
        return frame.iloc[:frame.index.searchsorted(cutoff, side="right")]
    return frame.loc[:cutoff]


def post_entry_window(
    frame: pd.DataFrame, entry: pd.Timestamp, deadline: pd.Timestamp,
) -> pd.DataFrame:
    """Rows after entry up to and including deadline, in original order."""
    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.is_monotonic_increasing:
        left = frame.index.searchsorted(entry, side="right")
        right = frame.index.searchsorted(deadline, side="right")
        return frame.iloc[left:right]
    return frame.loc[(frame.index > entry) & (frame.index <= deadline)]


def previous_structure_level(
    frame: pd.DataFrame, cutoff: pd.Timestamp, lookback: int, direction: str,
) -> float:
    """Historical prior-candle swing level; cutoff candle itself is excluded."""
    if frame.empty:
        return math.nan
    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.is_monotonic_increasing:
        end = frame.index.searchsorted(cutoff, side="left")
        prior = frame.iloc[max(0, end-lookback):end]
    else:
        prior = frame.loc[frame.index < cutoff].tail(lookback)
    if prior.empty:
        return math.nan
    if direction == "CALL":
        return float(prior["low"].min())
    return float(prior["high"].max())


def latest_completed_close(
    frame: pd.DataFrame, cutoff: pd.Timestamp, fallback: float,
) -> float:
    """Match close.dropna().iloc[-1] without constructing a full prior slice."""
    if not (isinstance(frame.index, pd.DatetimeIndex) and frame.index.is_monotonic_increasing):
        values = frame.loc[:cutoff, "close"].dropna()
        return float(values.iloc[-1]) if not values.empty else fallback
    end = frame.index.searchsorted(cutoff, side="right")
    closes = frame["close"]
    for i in range(end - 1, -1, -1):
        value = closes.iloc[i]
        if pd.notna(value):
            return float(value)
    return fallback
