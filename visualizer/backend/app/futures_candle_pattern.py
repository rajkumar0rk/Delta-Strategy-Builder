"""Bounded, completed-hour bearish continuation and 5m point-trailing research.

The input frame uses UTC 5m candle CLOSE timestamps. A completed hour must
contain exactly twelve consecutive 5m candles; missing or off-grid candles
invalidate the hour instead of allowing a partial bar or a stale pattern.
"""
from __future__ import annotations

from collections import deque
import math
import pandas as pd


FIVE_MINUTES = pd.Timedelta(minutes=5)
ONE_HOUR = pd.Timedelta(hours=1)


def body_eligible(bar, threshold_percent: float) -> bool:
    """True when the candle body is >= the configured % of its full range."""
    _, opened, high, low, closed = bar
    width = high - low
    return width > 0 and abs(closed - opened) * 100 >= threshold_percent * width


def completed_hour_patterns(frame, config, tick_size: float):
    """Index of final 5m bar -> immutable next-hour SHORT setup.

    One pass over 5m observations, O(N) time, O(1) live pattern state plus
    O(signals) output. No resampling at each bar; only fully closed UTC hours
    may arm next-open orders. No unconfirmed hourly candle is consulted.
    """
    result = {}
    hours = deque(maxlen=3)
    bucket = []
    bucket_start = None
    previous_hour_end = None
    for index, (ts, opened, high, low, closed) in enumerate(
        frame[['open', 'high', 'low', 'close']].itertuples(index=True, name=None)
    ):
        ts = pd.Timestamp(ts)
        start = (ts - FIVE_MINUTES).floor('h')
        if bucket_start != start:
            bucket_start = start
            bucket = []
        values = (ts, float(opened), float(high), float(low), float(closed))
        if not all(math.isfinite(v) for v in values[1:]):
            bucket = []
            continue
        bucket.append(values)
        if ts != start + ONE_HOUR:
            continue
        valid = (
            len(bucket) == 12
            and bucket[0][0] == start + FIVE_MINUTES
            and all(bucket[k][0] == bucket[k - 1][0] + FIVE_MINUTES for k in range(1, 12))
        )
        if not valid:
            hours.clear()
            previous_hour_end = None
            bucket = []
            continue
        hourly = (
            ts, bucket[0][1], max(x[2] for x in bucket),
            min(x[3] for x in bucket), bucket[-1][4]
        )
        if previous_hour_end is not None and ts != previous_hour_end + ONE_HOUR:
            hours.clear()
        previous_hour_end = ts
        hours.append(hourly)
        bucket = []
        count = config.entry_candle - 1
        if len(hours) < count:
            continue
        setup = list(hours)[-count:]
        c1, c2 = setup[:2]
        if not (c1[4] > c1[1] and c2[4] < c2[1] and c2[4] < c1[3]):
            continue
        if count == 3 and not setup[2][4] < setup[2][1]:
            continue
        if config.doji_filter_enabled and not all(
            body_eligible(candle, config.doji_threshold_percent) for candle in setup
        ):
            continue
        stop = (
            max(candle[2] for candle in setup)
            if config.stop_anchor == 'PATTERN_HIGHEST_HIGH'
            else setup[-1][2]
        ) + config.stop_buffer_ticks * tick_size
        if stop <= 0 or not math.isfinite(stop):
            continue
        result[index] = {
            # ENTRY_POINTS cannot be fixed until the actual next-open fill.
            'stop_price': None if config.stop_anchor == 'ENTRY_POINTS' else stop,
            'setup_time': ts.isoformat(),
            'entry_candle': config.entry_candle,
            'setup_highs': [candle[2] for candle in setup],
            'rule_risk': False,
            'candle_pattern': True,
            'reward_r_multiple': None,
            'take_profit_points': (
                config.fixed_target_points if config.take_profit_mode == 'FIXED_POINTS'
                else None
            ),
        }
    return result


def update_short_point_trail(position: dict, completed_bar, config, tick_size: float) -> str | None:
    """Activate/ratchet only AFTER the current bar's stop check.

    The revised protective stop is used by the caller starting on the NEXT
    5m OHLC interval. No intrabar activation or same-bar hindsight.
    """
    if config.take_profit_mode != 'TRAILING_POINTS':
        return None
    opened = float(completed_bar.open)
    closed = float(completed_bar.close)
    high = float(completed_bar.high)
    low = float(completed_bar.low)
    if not all(math.isfinite(v) for v in (opened, closed, high, low)):
        return None
    if config.trailing_ignore_doji and not body_eligible(
        (None, opened, high, low, closed), config.doji_threshold_percent
    ):
        return None
    entry = position['entry_price']
    activation = entry - config.activation_points
    if not position.get('pattern_profit_active'):
        if closed > activation:
            return None
        # Protect at least the activation distance when rounded to a price tick.
        floor_stop = math.floor(activation / tick_size + 1e-10) * tick_size
        if floor_stop <= 0:
            return None
        position['stop_price'] = round(min(position['stop_price'], floor_stop), 10)
        position['pattern_profit_active'] = True
        position['trailing_active'] = True
        return 'PATTERN_TRAIL_ACTIVATED'
    # SHORT trailing: lower completed CLOSE tightens the stop; it never rises.
    candidate = math.ceil((closed + config.pullback_points) / tick_size - 1e-10) * tick_size
    tightened = min(position['stop_price'], candidate)
    if tightened >= position['stop_price'] - 1e-10 or tightened <= 0:
        return None
    position['stop_price'] = round(tightened, 10)
    return 'PATTERN_TRAIL_RATCHET'
