from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .market_context_discovery import DISCOVERY_END, FINAL_END, VALIDATION_END


UTC = timezone.utc


def _bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close", "volume"])


def _resample(frame: pd.DataFrame, rule: str, expected: int) -> pd.DataFrame:
    result = frame.resample(rule, label="right", closed="right").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), count=("close", "count"),
    )
    return result.loc[result["count"] == expected].drop(columns="count")


def _indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    previous = result["close"].shift(1)
    result["tr"] = pd.concat([
        result["high"].sub(result["low"]),
        result["high"].sub(previous).abs(),
        result["low"].sub(previous).abs(),
    ], axis=1).max(axis=1)
    result["atr14"] = result["tr"].rolling(14, min_periods=14).mean()
    result["ema20"] = result["close"].ewm(span=20, adjust=False).mean()
    result["ema50"] = result["close"].ewm(span=50, adjust=False).mean()
    delta = result["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    result["rsi14"] = 100 - (100 / (1 + gain.div(loss.replace(0.0, np.nan))))
    mean = result["close"].rolling(20, min_periods=20).mean()
    std = result["close"].rolling(20, min_periods=20).std(ddof=0)
    result["bb_mid"] = mean
    result["bb_upper"] = mean + 2 * std
    result["bb_lower"] = mean - 2 * std
    result["bb_width"] = result["bb_upper"].sub(result["bb_lower"]).div(mean)
    return result


def _cooldown(mask: pd.Series, bars: int) -> pd.Series:
    selected = pd.Series(False, index=mask.index)
    last = -bars
    for position, value in enumerate(mask.fillna(False).to_numpy()):
        if value and position - last >= bars:
            selected.iloc[position] = True
            last = position
    return selected


def _stats(
    frame: pd.DataFrame,
    mask: pd.Series,
    direction: pd.Series,
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        signed = frame["close"].shift(-horizon).div(frame["close"]).sub(1).mul(direction)
        for name, start, end in (
            ("discovery", None, DISCOVERY_END),
            ("validation", DISCOVERY_END, VALIDATION_END),
            ("final_holdout", VALIDATION_END, FINAL_END),
        ):
            period = mask & (frame.index < end)
            if start is not None:
                period &= frame.index >= start
            values = signed.loc[period].dropna()
            rows.append({
                "segment": name,
                "horizon_bars": horizon,
                "signals": int(values.size),
                "win_rate_percent": float((values > 0).mean() * 100) if len(values) else None,
                "average_signed_return_percent": float(values.mean() * 100) if len(values) else None,
                "median_signed_return_percent": float(values.median() * 100) if len(values) else None,
            })
    return rows


def _directional_break(frame: pd.DataFrame, lookback: int) -> pd.Series:
    upper = frame["high"].shift(1).rolling(lookback, min_periods=lookback).max()
    lower = frame["low"].shift(1).rolling(lookback, min_periods=lookback).min()
    return pd.Series(np.where(frame["close"].gt(upper), 1.0,
                     np.where(frame["close"].lt(lower), -1.0, 0.0)), index=frame.index)


def _outer_close(frame: pd.DataFrame, direction: pd.Series, fraction: float) -> pd.Series:
    location = frame["close"].sub(frame["low"]).div(
        frame["high"].sub(frame["low"]).replace(0.0, np.nan)
    )
    return direction.gt(0).mul(location.ge(1 - fraction)) | direction.lt(0).mul(location.le(fraction))


def _trend_at(index: pd.DatetimeIndex, hourly: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    slope = hourly["ema20"].div(hourly["ema20"].shift(3)).sub(1)
    bull = hourly["ema20"].gt(hourly["ema50"]) & slope.gt(0)
    bear = hourly["ema20"].lt(hourly["ema50"]) & slope.lt(0)
    return bull.reindex(index, method="ffill"), bear.reindex(index, method="ffill")


def _opening_range(frame: pd.DataFrame, zone: str, opening: time) -> tuple[pd.Series, pd.Series]:
    local = frame.index.tz_convert(ZoneInfo(zone))
    dates = pd.Series(local.date, index=frame.index)
    minutes = local.hour * 60 + local.minute
    start_minute = opening.hour * 60 + opening.minute
    # Input timestamps are candle-close times. The 08:00-08:30 range is
    # therefore represented by closes at 08:05 through 08:30.
    range_mask = (minutes > start_minute) & (minutes <= start_minute + 30)
    trade_mask = (minutes > start_minute + 30) & (minutes <= start_minute + 150)
    direction = pd.Series(0.0, index=frame.index)
    selected = pd.Series(False, index=frame.index)
    for local_date in pd.unique(dates):
        same_day = dates.eq(local_date)
        range_rows = frame.loc[same_day & range_mask]
        if len(range_rows) != 6:
            continue
        upper, lower = range_rows["high"].max(), range_rows["low"].min()
        candidates = frame.loc[same_day & trade_mask]
        raw = pd.Series(np.where(candidates["close"].gt(upper), 1.0,
                        np.where(candidates["close"].lt(lower), -1.0, 0.0)), index=candidates.index)
        valid = raw.ne(0) & _outer_close(candidates, raw, 0.25)
        if valid.any():
            timestamp = valid.index[valid][0]
            selected.loc[timestamp] = True
            direction.loc[timestamp] = raw.loc[timestamp]
    return selected, direction


def _previous_day_breakout(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    daily = frame.resample("1D").agg(high=("high", "max"), low=("low", "min"))
    previous = daily.shift(1)
    day_keys = frame.index.floor("1D")
    previous_high = pd.Series(previous["high"].reindex(day_keys).to_numpy(), index=frame.index)
    previous_low = pd.Series(previous["low"].reindex(day_keys).to_numpy(), index=frame.index)
    raw = pd.Series(
        np.where(frame["close"].gt(previous_high), 1.0,
        np.where(frame["close"].lt(previous_low), -1.0, 0.0)),
        index=frame.index,
    )
    volume_ok = frame["volume"].ge(frame["volume"].shift(1).rolling(20).median())
    valid = raw.ne(0) & volume_ok & _outer_close(frame, raw, 0.25)
    selected = pd.Series(False, index=frame.index)
    direction = pd.Series(0.0, index=frame.index)
    for day in pd.unique(day_keys):
        candidates = valid & (day_keys == day)
        if candidates.any():
            timestamp = candidates.index[candidates][0]
            selected.loc[timestamp] = True
            direction.loc[timestamp] = raw.loc[timestamp]
    return selected, direction


def _london_false_break(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    local = frame.index.tz_convert(ZoneInfo("Europe/London"))
    dates = pd.Series(local.date, index=frame.index)
    minutes = local.hour * 60 + local.minute
    range_mask = (minutes > 8 * 60) & (minutes <= 8 * 60 + 30)
    trade_mask = (minutes > 8 * 60 + 30) & (minutes <= 10 * 60 + 30)
    selected = pd.Series(False, index=frame.index)
    direction = pd.Series(0.0, index=frame.index)
    location = frame["close"].sub(frame["low"]).div(
        frame["high"].sub(frame["low"]).replace(0.0, np.nan)
    )
    for local_date in pd.unique(dates):
        same_day = dates.eq(local_date)
        range_rows = frame.loc[same_day & range_mask]
        if len(range_rows) != 6:
            continue
        upper, lower = range_rows["high"].max(), range_rows["low"].min()
        candidates = frame.loc[same_day & trade_mask]
        bull = (
            candidates["low"].lt(lower)
            & candidates["close"].gt(lower)
            & candidates["close"].gt(candidates["open"])
            & location.loc[candidates.index].ge(0.50)
        )
        bear = (
            candidates["high"].gt(upper)
            & candidates["close"].lt(upper)
            & candidates["close"].lt(candidates["open"])
            & location.loc[candidates.index].le(0.50)
        )
        valid = bull | bear
        if valid.any():
            timestamp = valid.index[valid][0]
            selected.loc[timestamp] = True
            direction.loc[timestamp] = 1.0 if bull.loc[timestamp] else -1.0
    return selected, direction


def _new_york_aligned_with_london(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    selected, direction = _opening_range(
        frame, "America/New_York", time(9, 30)
    )
    aligned = selected.copy()
    london = ZoneInfo("Europe/London")
    for timestamp in frame.index[selected]:
        london_date = timestamp.tz_convert(london).date()
        london_start = pd.Timestamp(
            datetime.combine(london_date, time(8, 0)), tz=london
        ).tz_convert("UTC")
        morning = frame.loc[(frame.index > london_start) & (frame.index <= timestamp)]
        if morning.empty:
            aligned.loc[timestamp] = False
            continue
        london_direction = np.sign(morning["close"].iloc[-1] - morning["open"].iloc[0])
        if london_direction == 0 or london_direction != direction.loc[timestamp]:
            aligned.loc[timestamp] = False
    return aligned, direction


def run(path: Path) -> dict[str, object]:
    five = _indicators(_bars(path))
    fifteen = _indicators(_resample(five, "15min", 3))
    hourly = _indicators(_resample(five, "1h", 12))
    results: dict[str, list[dict[str, object]]] = {}

    direction = _directional_break(five, 12)
    bull_trend, bear_trend = _trend_at(five.index, hourly)
    volume_ok = five["volume"].ge(five["volume"].shift(1).rolling(20).median())
    trend_ok = direction.gt(0).mul(bull_trend) | direction.lt(0).mul(bear_trend)
    mask = direction.ne(0) & five["tr"].ge(five["atr14"]) & volume_ok
    mask &= _outer_close(five, direction, 0.25) & trend_ok
    mask = _cooldown(mask, 12)
    results["five_minute_trend_expansion"] = _stats(five, mask, direction, (3, 6, 12))

    direction = _directional_break(five, 20)
    low_bandwidth = five["bb_width"].le(
        five["bb_width"].shift(1).rolling(288, min_periods=288).quantile(0.20)
    )
    mask = direction.ne(0) & low_bandwidth & five["tr"].ge(1.2 * five["atr14"]) & volume_ok
    mask &= _outer_close(five, direction, 0.25)
    mask = _cooldown(mask, 12)
    results["five_minute_compression_breakout"] = _stats(five, mask, direction, (3, 6, 12))

    direction = _directional_break(fifteen, 8)
    slope = fifteen["ema20"].div(fifteen["ema20"].shift(4)).sub(1)
    trend_ok = direction.gt(0).mul(fifteen["ema20"].gt(fifteen["ema50"]) & slope.gt(0))
    trend_ok |= direction.lt(0).mul(fifteen["ema20"].lt(fifteen["ema50"]) & slope.lt(0))
    volume_ok_15 = fifteen["volume"].ge(fifteen["volume"].shift(1).rolling(20).median())
    mask = direction.ne(0) & trend_ok & fifteen["tr"].ge(fifteen["atr14"]) & volume_ok_15
    mask &= _outer_close(fifteen, direction, 0.25)
    mask = _cooldown(mask, 4)
    results["fifteen_minute_trend_breakout"] = _stats(fifteen, mask, direction, (1, 2, 4))

    hourly_separation = hourly["ema20"].sub(hourly["ema50"]).abs().div(hourly["close"])
    hourly_slope = hourly["ema20"].div(hourly["ema20"].shift(3)).sub(1).abs()
    neutral = (hourly_separation.le(0.002) & hourly_slope.le(0.0015)).reindex(five.index, method="ffill")
    prior_low = five["close"].shift(1).lt(five["bb_lower"].shift(1)) & five["rsi14"].shift(1).lt(30)
    prior_high = five["close"].shift(1).gt(five["bb_upper"].shift(1)) & five["rsi14"].shift(1).gt(70)
    bull = prior_low & five["close"].gt(five["bb_lower"]) & five["close"].gt(five["open"])
    bear = prior_high & five["close"].lt(five["bb_upper"]) & five["close"].lt(five["open"])
    direction = pd.Series(np.where(bull, 1.0, np.where(bear, -1.0, 0.0)), index=five.index)
    mask = _cooldown(direction.ne(0) & neutral, 6)
    results["neutral_exhaustion_reversal"] = _stats(five, mask, direction, (3, 6, 12))

    slots = [five.index.hour, five.index.minute]
    slot_volume = five.groupby(slots)["volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).median()
    )
    candle_direction = pd.Series(np.sign(five["close"].sub(five["open"])), index=five.index)
    body_ratio = five["close"].sub(five["open"]).abs().div(
        five["high"].sub(five["low"]).replace(0.0, np.nan)
    )
    impulse = five["tr"].ge(1.5 * five["atr14"]) & five["volume"].ge(2 * slot_volume)
    impulse &= body_ratio.ge(0.60) & _outer_close(five, candle_direction, 0.20)
    mask = _cooldown(impulse, 6)
    results["abnormal_volume_impulse"] = _stats(five, mask, candle_direction, (3, 6, 12))

    midpoint = five["high"].shift(1).add(five["low"].shift(1)).div(2)
    prior_direction = candle_direction.shift(1)
    failed = impulse.shift(1).fillna(False) & (
        prior_direction.gt(0).mul(five["close"].lt(midpoint))
        | prior_direction.lt(0).mul(five["close"].gt(midpoint))
    )
    direction = -prior_direction
    mask = _cooldown(failed, 6)
    results["failed_impulse_reversal"] = _stats(five, mask, direction, (3, 6, 12))

    for name, zone, opening in (
        ("new_york_opening_range", "America/New_York", time(9, 30)),
        ("london_opening_range", "Europe/London", time(8, 0)),
    ):
        mask, direction = _opening_range(five, zone, opening)
        results[name] = _stats(five, mask, direction, (6, 12, 24))

    mask, direction = _opening_range(five, "Asia/Tokyo", time(9, 0))
    results["tokyo_opening_range"] = _stats(five, mask, direction, (6, 12, 24))

    mask, direction = _previous_day_breakout(five)
    results["previous_utc_day_breakout"] = _stats(five, mask, direction, (6, 12, 24))

    mask, direction = _london_false_break(five)
    results["london_false_break_reversal"] = _stats(five, mask, direction, (6, 12, 24))

    mask, direction = _new_york_aligned_with_london(five)
    results["new_york_breakout_london_aligned"] = _stats(
        five, mask, direction, (6, 12, 24)
    )

    direction = _directional_break(hourly, 24)
    slope = hourly["ema20"].div(hourly["ema20"].shift(3)).sub(1)
    trend_ok = direction.gt(0).mul(hourly["ema20"].gt(hourly["ema50"]) & slope.gt(0))
    trend_ok |= direction.lt(0).mul(hourly["ema20"].lt(hourly["ema50"]) & slope.lt(0))
    volume_ok_hour = hourly["volume"].ge(hourly["volume"].shift(1).rolling(20).median())
    mask = direction.ne(0) & trend_ok & hourly["tr"].ge(hourly["atr14"]) & volume_ok_hour
    mask &= _outer_close(hourly, direction, 0.25)
    mask = _cooldown(mask, 1)
    results["one_hour_structure_breakout"] = _stats(hourly, mask, direction, (1, 4, 8))

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "method": "Frozen OHLCV hypotheses rerun on continuity-validated five-minute history.",
        "source_rows": len(five),
        "hypotheses": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rerun frozen OHLCV discovery hypotheses")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report["hypotheses"], indent=2, allow_nan=False))
    print(f"OHLCV discovery report complete: {args.output.resolve()}")


if __name__ == "__main__":
    main()
