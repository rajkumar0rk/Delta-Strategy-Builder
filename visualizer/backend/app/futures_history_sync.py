"""Bridge between Strategy Lab archive auto-repair and reusable free futures sync."""
from __future__ import annotations

from .config import data_root
from backtest.futures_history import sync_futures_observations


def ensure_futures_observations(start, end, progress=None):
    if progress:
        progress("Checking free Delta futures mark/index/funding-rate history…", 9,
                 "FUTURES_DATA_SYNC", "Reuse valid stored daily shards")
    def emit(message):
        if progress:
            progress(message, 12, "FUTURES_DATA_SYNC",
                     "Load BTC candles and validate funding assumptions")
    return sync_futures_observations(data_root(), start, end, progress=emit)
