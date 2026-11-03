"""Bounded-memory iterator of complete legacy EMA/VWAP H6 indicators.

Unlike indicators(..., indicator_chunk_rows=N), this iterator NEVER
concatenates all historical candles. It carries only recursive core state,
the current IST VWAP session and 20 preceding bars needed for rolling
Stoch RSI, volume median, and direction/crossover continuity.

The existing full-frame research runner is intentionally unchanged. Direct
use is for indicator-only workflows and upcoming incremental signal work.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd

from .ema_vwap_research import IST, complete_indicators_from_core
from .legacy_indicator_stream import iter_streamed_core_chunks


_CORE_COLUMNS = (
    "open", "high", "low", "close", "volume",
    "ema9", "ema20", "ema50", "rsi14",
    "atr14", "macd", "macd_signal",
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
        calculated = complete_indicators_from_core(
            core.copy(), compact_directions=compact_directions,
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
            carry = core.iloc[keep_from:][list(_CORE_COLUMNS)].copy()
