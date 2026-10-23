"""Calendar-day snapshots built exclusively from already completed history."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Only registered symbols can select a symbol-derived trading calendar.
# Delta BTCUSD is 24/7: the UTC rollover below is a *chart convention*,
# not an exchange open/close or an option expiry/settlement time.
SYMBOL_SESSIONS = {
    'BTCUSD': ('UTC', '00:00', '00:00', tuple(range(7))),
}


def _clock_minutes(text: str) -> int:
    import re
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):(?:[0-5][0-9])', text):
        raise ValueError('Session clock must be HH:MM in 24-hour format')
    hour, minute = map(int, text.split(':'))
    if minute % 5:
        raise ValueError('Session clock must align with the source 5-minute grid')
    return hour * 60 + minute


def _weekdays(text: str) -> tuple[int, ...]:
    import re
    if not re.fullmatch(r'[0-6](?:,[0-6])*', text):
        raise ValueError('session_weekdays must be comma-separated integers 0..6')
    days = tuple(int(v) for v in text.split(','))
    if len(set(days)) != len(days):
        raise ValueError('session_weekdays must not contain duplicates')
    return days


class DayLevelParams(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    timezone: str = 'Asia/Kolkata'
    day_boundary_mode: str = 'CALENDAR'
    symbol: str = 'BTCUSD'
    session_timezone: str = 'UTC'
    session_open: str = '00:00'
    session_close: str = '00:00'
    session_weekdays: str = '0,1,2,3,4,5,6'
    pivot_left: int = Field(default=3, ge=1, le=50)
    pivot_right: int = Field(default=3, ge=1, le=50)
    lookback_days: int = Field(default=30, ge=1, le=60)
    warning_points: float = Field(default=100.0, ge=0)

    @field_validator('timezone', 'session_timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('DAY_LEVELS timezone must be an IANA timezone') from exc
        return value

    @model_validator(mode='after')
    def validate_day_boundary(self):
        if self.day_boundary_mode not in ('CALENDAR', 'SYMBOL_SESSION', 'CUSTOM_SESSION'):
            raise ValueError('Unknown day_boundary_mode; expected CALENDAR, SYMBOL_SESSION or CUSTOM_SESSION')
        if self.day_boundary_mode == 'SYMBOL_SESSION' and self.symbol not in SYMBOL_SESSIONS:
            raise ValueError(f'No configured symbol session for {self.symbol!r}; select CUSTOM_SESSION')
        if self.day_boundary_mode == 'CUSTOM_SESSION':
            _clock_minutes(self.session_open)
            _clock_minutes(self.session_close)
            _weekdays(self.session_weekdays)
        return self


def _calendar_spec(p: DayLevelParams):
    if p.day_boundary_mode == 'CALENDAR':
        return ZoneInfo(p.timezone), 0, 0, tuple(range(7)), False
    if p.day_boundary_mode == 'SYMBOL_SESSION':
        zone, start, end, days = SYMBOL_SESSIONS[p.symbol]
        return ZoneInfo(zone), _clock_minutes(start), _clock_minutes(end), days, False
    return ZoneInfo(p.session_timezone), _clock_minutes(p.session_open), _clock_minutes(p.session_close), _weekdays(p.session_weekdays), True


def _session_bounds(day: date, spec):
    zone, open_min, close_min, _, _ = spec
    opening = pd.Timestamp(day).tz_localize(zone) + pd.Timedelta(minutes=open_min)
    end_day = day + timedelta(days=1) if close_min <= open_min else day
    closing = pd.Timestamp(end_day).tz_localize(zone) + pd.Timedelta(minutes=close_min)
    return opening.tz_convert('UTC'), closing.tz_convert('UTC')


def _session_labels(index: pd.DatetimeIndex, bar_minutes: int, spec) -> list[date | None]:
    """Assign *completed* bars to sessions using the candle's OPEN timestamp.

    CALENDAR and 24h sessions preserve the prior open-day policy on
    higher-timeframe candles straddling rollover. Finite custom sessions
    require the entire candle to fit inside that session.
    """
    zone, open_min, close_min, weekdays, finite = spec
    openings = (index - pd.Timedelta(minutes=bar_minutes)).tz_convert(zone)
    allowed = set(weekdays)
    bounds: dict[date, tuple[pd.Timestamp, pd.Timestamp]] = {}
    labels = []
    for opened, closed in zip(openings, index):
        minute = opened.hour * 60 + opened.minute
        day = opened.date()
        if close_min == open_min:  # continuous 24-hour sessions
            if minute < open_min:
                day -= timedelta(days=1)
        elif close_min > open_min:  # intraday session
            if not open_min <= minute < close_min:
                labels.append(None)
                continue
        elif minute < close_min:  # after local midnight, before overnight close
            day -= timedelta(days=1)
        elif minute < open_min:   # downtime before the next open
            labels.append(None)
            continue
        if day.weekday() not in allowed:
            labels.append(None)
            continue
        if day not in bounds:
            bounds[day] = _session_bounds(day, spec)
        start, end = bounds[day]
        stamp = opened.tz_convert('UTC')
        if stamp < start or stamp >= end or (finite and closed > end):
            labels.append(None)
        else:
            labels.append(day)
    return labels


def _previous_session(day: date, spec) -> date:
    weekdays = set(spec[3])
    preceding = day - timedelta(days=1)
    while preceding.weekday() not in weekdays:
        preceding -= timedelta(days=1)
    return preceding


LEVELS = ('previous_day_swing_high', 'previous_day_swing_low',
          'older_swing_high', 'older_swing_low')
DISPLAY_OUTPUTS = ('previous_day_high', 'previous_day_low', *LEVELS)
OUTPUTS = (*DISPLAY_OUTPUTS, 'day_id', 'previous_day_ready', 'older_history_ready',
           *(f'{level}_{kind}' for level in LEVELS for kind in ('distance', 'near', 'touch')))


def _utc_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex) or not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError('DAY_LEVELS requires unique, ordered candle-close timestamps')
    return index.tz_localize('UTC') if index.tz is None else index.tz_convert('UTC')


def compute_day_levels(frame: pd.DataFrame, pivots: pd.DataFrame,
                       source: pd.DataFrame, params: dict, strategy_minutes: int,
                       pivot_minutes: int, confirmations: tuple,
                       progress: Callable[[str], None] | None = None) -> dict[str, pd.Series]:
    """Use raw 5m bars for calendar ranges, native bars for confirmed pivots.

    A strategy/pivot candle belongs to the configured day/session of its OPEN. Thus a
    strategy candle straddling local midnight still uses the old snapshot,
    which was known before that candle opened. New snapshots only include
    pivot confirmations at or before the new local day's midnight.
    """
    p = DayLevelParams.model_validate(params)
    index, pivot_index, raw_index = _utc_index(frame), _utc_index(pivots), _utc_index(source)
    if not (raw_index == raw_index.floor('5min')).all():
        raise ValueError('DAY_LEVELS daily source must contain on-grid 5m closes')
    out = {key: np.full(len(frame), np.nan) for key in OUTPUTS}
    if frame.empty:
        return {key: pd.Series(values, index=frame.index) for key, values in out.items()}
    spec = _calendar_spec(p)
    target_days = _session_labels(index, strategy_minutes, spec)
    raw_days = _session_labels(raw_index, 5, spec)
    pivot_days = np.array([d.toordinal() if d is not None else -1
                           for d in _session_labels(pivot_index, pivot_minutes, spec)])
    raw_values = source[['open', 'high', 'low', 'close']].to_numpy(float)
    valid_raw = (np.isfinite(raw_values).all(axis=1) &
                 (raw_values[:, 1] >= np.maximum(raw_values[:, 0], raw_values[:, 3])) &
                 (raw_values[:, 2] <= np.minimum(raw_values[:, 0], raw_values[:, 3])))
    daily = {}
    raw_valid = [i for i, d in enumerate(raw_days) if d is not None]
    raw_groups = pd.Series(raw_valid, index=[raw_days[i] for i in raw_valid]).groupby(level=0, sort=False)
    for number, (day, positions) in enumerate(raw_groups):
        if progress and number % 32 == 0:
            progress('Checking complete calendar days for historical levels…')
        start, end = _session_bounds(day, spec)
        if start != start.floor('5min') or end != end.floor('5min'):
            raise ValueError('DAY_LEVELS session boundaries must align with the downloaded 5m grid')
        expected = pd.date_range(start + pd.Timedelta(minutes=5), end, freq='5min')
        positions = positions.to_numpy(int)
        actual = raw_index[positions]
        complete = (len(actual) == len(expected) and bool((actual == expected).all())
                    and bool(valid_raw[positions].all()))
        daily[day] = (complete, float(source.high.iloc[positions].max()),
                      float(source.low.iloc[positions].min()))

    # Discard confirmations whose entire left/right window is not contiguous
    # and finite. A missing native bar must not shorten the confirmation delay.
    hf, lf, hp, lp = confirmations
    finite = np.isfinite(pivots[['high', 'low']].to_numpy(float)).all(axis=1)
    bad_values = np.r_[0, np.cumsum(~finite)]
    bad_edges = np.r_[0, np.cumsum(np.asarray(pivot_index[1:] - pivot_index[:-1]) !=
                                    pd.Timedelta(minutes=pivot_minutes))]
    valid_event = np.zeros(len(pivots), dtype=bool)
    for confirm in np.flatnonzero((hf > 0) | (lf > 0)):
        candidate = confirm - p.pivot_right
        first = candidate - p.pivot_left
        if first >= 0 and bad_values[confirm + 1] == bad_values[first] and bad_edges[confirm] == bad_edges[first]:
            valid_event[confirm] = True
    events = {}
    for key, flags, prices in (('high', hf, hp), ('low', lf, lp)):
        confirms = np.flatnonzero((flags > 0) & valid_event)
        candidates = confirms - p.pivot_right
        events[key] = (pivot_index[confirms], pivot_days[candidates], prices[confirms])

    target_valid = [i for i, d in enumerate(target_days) if d is not None]
    groups = pd.Series(target_valid, index=[target_days[i] for i in target_valid]).groupby(level=0, sort=False)
    for number, (day, positions) in enumerate(groups):
        if progress and number % 32 == 0:
            progress('Freezing daily levels and searching older confirmed swings…')
        positions = positions.to_numpy(int)
        cutoff, _ = _session_bounds(day, spec)
        yesterday = _previous_session(day, spec)
        first_day = yesterday - timedelta(days=p.lookback_days)
        ready, high, low = daily.get(yesterday, (False, np.nan, np.nan))
        older_ready = ready and all(
            daily.get(yesterday - timedelta(days=age), (False,))[0]
            for age in range(1, p.lookback_days + 1)
            if (yesterday - timedelta(days=age)).weekday() in spec[3]
        )
        out['day_id'][positions] = day.toordinal()
        out['previous_day_ready'][positions] = float(ready)
        out['older_history_ready'][positions] = float(older_ready)
        if not ready:
            continue
        out['previous_day_high'][positions] = high
        out['previous_day_low'][positions] = low
        for side, boundary in (('high', high), ('low', low)):
            confirmed_at, occurred_on, prices = events[side]
            known = np.asarray(confirmed_at <= cutoff)
            previous = prices[known & (occurred_on == yesterday.toordinal())]
            if len(previous):
                out[f'previous_day_swing_{side}'][positions] = previous.max() if side == 'high' else previous.min()
            if older_ready:
                qualifies = (prices > boundary) if side == 'high' else (prices < boundary)
                candidates = prices[known & (occurred_on < yesterday.toordinal()) &
                                    (occurred_on >= first_day.toordinal()) & qualifies]
                if len(candidates):
                    # Events are chronological: first found searching backward,
                    # NOT the closest price and NOT the most extreme price.
                    out[f'older_swing_{side}'][positions] = candidates[-1]

    high, low = frame.high.to_numpy(float), frame.low.to_numpy(float)
    valid_bar = np.isfinite(high) & np.isfinite(low) & (low <= high)
    for level in LEVELS:
        value = out[level]
        valid = valid_bar & np.isfinite(value)
        distance = np.maximum(np.maximum(low - value, value - high), 0.0)
        out[f'{level}_distance'] = np.where(valid, distance, np.nan)
        out[f'{level}_touch'] = np.where(valid, (distance == 0).astype(float), np.nan)
        # A candle that touches gets confirmation only, not a premature warning.
        out[f'{level}_near'] = np.where(valid, ((distance > 0) & (distance <= p.warning_points)).astype(float), np.nan)
    return {key: pd.Series(values, index=frame.index) for key, values in out.items()}
