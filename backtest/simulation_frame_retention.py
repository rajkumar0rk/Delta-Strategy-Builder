"""Opt-in candle frame reduction after full indicator/signal evaluation.

Do not prune input candles before indicator calculation: EMA, Wilder RSI/ATR,
session VWAP and derived entries require original history. This pass is only
for trade simulation once signal diagnostics, event regimes and options have
already been determined.
"""
from __future__ import annotations

import pandas as pd


# All columns read by simulate_trade and its helper/exit functions. Original
# order is preserved by selecting them from the source frame in-place order.
_SIMULATION_COLUMNS = frozenset({
    "high", "low", "close", "volume", "ema9", "ema20", "ema50",
    "vwap", "rsi14", "atr14", "volume_median20_prior",
    "macd", "macd_signal",
})


def prepare_simulation_frame(frame: pd.DataFrame, events_by_configuration,
                             scenarios) -> pd.DataFrame:
    """Detach unused candles/columns while preserving all trade lookbacks.

    The earliest entry signal determines the left boundary. We retain enough
    preceding completed rows for *every* scenario's previous structure level
    (even when early failure is disabled, for its reported reference level)
    and directional confirmation. All future rows are preserved for holds
    that extend beyond the requested backtest window or have no time limit.

    For unsupported/unsorted input indexes or missing expected columns,
    return the original frame, without guessing or silently altering order.
    """
    if (
        not isinstance(frame, pd.DataFrame)
        or not isinstance(frame.index, pd.DatetimeIndex)
        or not frame.index.is_monotonic_increasing
        or frame.index.tz is None
        or not _SIMULATION_COLUMNS.issubset(frame.columns)
    ):
        return frame

    first_signal = min(
        (event.timestamp_ns
         for events in events_by_configuration.values() for event in events),
        default=None,
    )
    if first_signal is None:
        return frame
    earliest = pd.Timestamp(first_signal, unit="ns", tz="UTC")
    first_position = int(frame.index.searchsorted(earliest, side="left"))
    longest_prior = max(
        (
            max(
                scenario.early_failure.structure_lookback_candles,
                scenario.directional_confirmation_minutes // 5 + 1
                if scenario.directional_confirmation_minutes > 0 else 1,
            )
            for scenario in scenarios
        ),
        default=1,
    )
    first_kept = max(0, first_position - longest_prior)
    columns = [name for name in frame.columns if name in _SIMULATION_COLUMNS]
    # .copy() breaks ownership of discarded Pandas blocks; a pure .iloc view
    # can keep the full historical source buffers alive.
    return frame.iloc[first_kept:][columns].copy()
