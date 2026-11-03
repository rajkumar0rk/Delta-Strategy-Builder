"""Bounded-memory iterator of complete legacy EMA/VWAP H6 indicators.

Unlike indicators(..., indicator_chunk_rows=N), this iterator NEVER
concatenates all historical candles. It carries only recursive core state,
the current IST VWAP session and 20 preceding bars needed for rolling
Stoch RSI, volume median, and direction/crossover continuity. The Stoch RSI K/D 3-bar
smoothers retain their compensated running-sum state across all chunks.

The existing full-frame research runner is intentionally unchanged. Direct
use is for indicator-only workflows and upcoming incremental signal work.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
import math

import pandas as pd

from .ema_vwap_research import IST, complete_indicators_from_core
from .legacy_indicator_stream import iter_streamed_core_chunks
from .compensated_rolling_mean import CompensatedRollingMean


_CORE_COLUMNS = (
    "open", "high", "low", "close", "volume",
    "ema9", "ema20", "ema50", "rsi14",
    "atr14", "macd", "macd_signal",
    "stoch_rsi_k", "stoch_rsi_d",
)

# The last D stochastic value needs 13 RSI samples for a Stoch window,
# 2 for K, and 2 for D. The prior-volume median needs 20 earlier volumes,
# and direction entry signals need the preceding row.
_ROLLING_CONTEXT = 20


def iter_complete_indicator_chunks(
    path: Path, *,
    chunk_rows: int = 512,
    max_session_rows: int = 4096,
    compact_directions: bool = False,
    retention_observer: Callable[[dict[str, int]], None] | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield complete indicator DataFrames, one input batch at a time.

    For correctly ordered normalized UTC candles, an emitted row has the
    same indicator semantics as full-frame indicators(path), including
    the first candle of a new IST session. The active in-memory working
    frame has at most chunk_rows + max_session_rows + 20 rows.

    Unsupported input order, timezone-free timestamps and overlong
    sessions fail closed; no rows are silently truncated or reordered.
    """
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ValueError("chunk_rows must be a positive integer")
    if type(max_session_rows) is not int or max_session_rows < 1:
        raise ValueError("max_session_rows must be a positive integer")
    carry: pd.DataFrame | None = None
    stoch_k = CompensatedRollingMean(3)
    stoch_d = CompensatedRollingMean(3)
    for new_core in iter_streamed_core_chunks(path, chunk_rows):
        history_rows = len(carry) if carry is not None else 0
        core = (
            pd.concat((carry, new_core), axis=0)
            if carry is not None and not carry.empty
            else new_core
        )
        # Date order is monotonic for an ordered timezone-aware index.
        dates = core.index.tz_convert(IST).date
        counts = pd.Series(dates).value_counts()
        if not counts.empty and int(counts.max()) > max_session_rows:
            raise ValueError("STREAMED_INDICATOR_SESSION_ROW_LIMIT_EXCEEDED")
        # Recompute only the 14-bar Stoch RSI normalization from bounded RSI
        # context. Pandas' 3-bar rolling means, unlike rolling min/max, have
        # compensated accumulators whose floating-point state depends on ALL
        # preceding input. Carry both smoothing accumulators continuously.
        rsi_values = core["rsi14"]
        lowest = rsi_values.rolling(14, min_periods=14).min()
        highest = rsi_values.rolling(14, min_periods=14).max()
        denominator = (highest - lowest).replace(0.0, math.nan)
        raw = 100.0 * (rsi_values - lowest) / denominator
        current_k: list[float] = []
        current_d: list[float] = []
        for value in raw.iloc[history_rows:]:
            k = stoch_k.update(float(value))
            current_k.append(k)
            current_d.append(stoch_d.update(k))
        previous_k = carry["stoch_rsi_k"].tolist() if carry is not None else []
        previous_d = carry["stoch_rsi_d"].tolist() if carry is not None else []
        calculated = complete_indicators_from_core(
            core.copy(), compact_directions=compact_directions,
            stoch_k_d=(
                previous_k + current_k,
                previous_d + current_d,
            ),
        )
        produced = calculated.iloc[history_rows:].copy()
        if retention_observer is not None:
            retention_observer({
                "input_chunk_rows": len(new_core),
                "context_rows": len(core),
                "previous_context_rows": history_rows,
                "emitted_rows": len(produced),
            })
        yield produced
        if len(core):
            latest_date = dates[-1]
            current_day_rows = 0
            for date in reversed(dates):
                if date != latest_date:
                    break
                current_day_rows += 1
            current_day_start = len(core) - current_day_rows
            keep_from = max(0, current_day_start - _ROLLING_CONTEXT)
            carry = calculated.iloc[keep_from:][list(_CORE_COLUMNS)].copy()
