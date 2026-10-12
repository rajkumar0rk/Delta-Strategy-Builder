"""Shared no-look-ahead warm-up policy for chart preview and backtests.

These functions never generate market data and never widen the EXECUTION universe:
historical archive neighbors are read for underlying indicator context only.
"""
from __future__ import annotations

import pandas as pd

from .data_store import DataStore
from .indicators import CATALOG

TF_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}
HISTORY_LIMIT = 20000


def required_warmup_candles(instances, timeframe: str, *, minimum: int = 500, strategy=None) -> int:
    """Return a conservative strategy-candle lookback for stable indicator seeds.

    Includes the catalog defaults, not just parameters explicitly overridden by
    the caller. Higher-timeframe lookbacks are converted to base-candle units.
    The 5x heuristic is a convergence target, not a mathematical guarantee.
    """
    base = TF_MINUTES[timeframe]
    required = max(0, int(minimum))
    if required > HISTORY_LIMIT:
        raise ValueError(f"Warm-up minimum exceeds {HISTORY_LIMIT} candles")
    for inst in instances:
        definition = CATALOG.get(inst.kind)
        if definition is None:
            continue  # indicator validation happens in compute_indicators()
        native_tf = timeframe if inst.timeframe == "strategy" else str(inst.timeframe)
        if native_tf not in TF_MINUTES:
            raise ValueError(f"Unsupported indicator timeframe {native_tf}")
        ratio = TF_MINUTES[native_tf] // base
        if TF_MINUTES[native_tf] % base or ratio < 1:
            raise ValueError(f"Indicator {inst.id} timeframe must be a multiple of {timeframe}")
        params = {key: val["default"] for key, val in definition.params.items()}
        params.update(inst.params)
        periods = []
        for key, value in params.items():
            if not any(term in key.lower() for term in
                       ("period", "lookback", "window", "length", "fast", "slow", "signal",
                        "smooth", "pivot_left", "pivot_right", "slope_bars")):
                continue
            try:
                periods.append(max(0, int(float(value))))
            except (TypeError, ValueError):
                pass
        # Composed smoothers (ADX, Stoch RSI, MACD) need multiple initialization
        # stages; 5x the largest constituent is an intentionally conservative
        # approximation, with the available-history warning retained.
        horizon = max(periods, default=0)
        required = max(required, (5 * horizon + 2) * ratio)

    if strategy is not None:
        def rule_horizon(group):
            if group is None:
                return 0
            offsets = [int(c.lookback_bars) + max(c.left_offset, c.right_offset)
                       for c in group.conditions]
            return max([*offsets, *(rule_horizon(g) for g in group.groups)], default=0)
        for name in ("call_entry", "put_entry", "call_exit", "put_exit",
                     "no_trade", "call_no_trade", "put_no_trade"):
            required = max(required, rule_horizon(getattr(strategy, name, None)) + 2)
        for alert in getattr(strategy, "alerts", []):
            if alert.enabled and alert.source == "LEGACY_CUSTOM":
                required = max(required, rule_horizon(alert.conditions) + 2)
        for side in ("call", "put"):
            score = getattr(strategy, f"{side}_big_trend_score", None)
            if score is not None and score.enabled:
                required = max(required, int(score.persistence_window) + 2)
    if required > HISTORY_LIMIT:
        raise ValueError(
            f"Warm-up requires {required} {timeframe} candles, exceeding {HISTORY_LIMIT}; "
            "reduce indicator lookbacks/timeframes or raise the supported cap deliberately"
        )
    return required


def historical_bar_sources(store: DataStore, trading_parts, start: str,
                           timeframe: str, warmup_candles: int, *, archive_neighbors: bool):
    """Extend the *bar-only* source to older catalog segments when allowed.

    Option selection and preflight still use the original trading_parts. An
    explicit SINGLE/MULTI dataset selection is not silently expanded.
    """
    if not archive_neighbors or warmup_candles <= 0:
        return list(trading_parts)
    start_ts = pd.Timestamp(start)
    if start_ts.tz is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    history_start = start_ts - pd.Timedelta(minutes=(warmup_candles + 1) * TF_MINUTES[timeframe])
    chosen = {p.id: p for p in trading_parts}
    for part in store.discover():
        if part.id in chosen or not part.catalog_start or not part.catalog_end_exclusive:
            continue
        left = pd.Timestamp(part.catalog_start)
        right = pd.Timestamp(part.catalog_end_exclusive)
        if left < start_ts and right > history_start and part.bars.exists():
            chosen[part.id] = part
    return list(chosen.values())


def warmup_diagnostics(bars: pd.DataFrame, start: str, timeframe: str,
                       requested: int) -> dict:
    cutoff = pd.Timestamp(start)
    cutoff = cutoff.tz_localize("UTC") if cutoff.tz is None else cutoff.tz_convert("UTC")
    prior = bars.index[bars.index < cutoff]
    step = TF_MINUTES[timeframe]
    # With close timestamps, a candle closing AT start is tradable and must
    # not be counted as a warm-up candle.
    last_expected = cutoff.ceil(f"{step}min") - pd.Timedelta(minutes=step)
    expected = pd.date_range(end=last_expected, periods=requested, freq=f"{step}min", tz="UTC") if requested else pd.DatetimeIndex([], tz="UTC")
    recent = prior[-requested:] if requested else prior[:0]
    complete = bool(requested == 0 or (len(recent) == requested and recent.equals(expected)))
    return {
        "requested_candles": int(requested),
        "available_candles": int(len(prior)),
        "contiguous": complete,
        "timeframe": timeframe,
        "first_available": prior[0].isoformat() if len(prior) else None,
        "last_available": prior[-1].isoformat() if len(prior) else None,
    }
