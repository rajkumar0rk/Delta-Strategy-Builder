from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


UTC = timezone.utc
DISCOVERY_END = pd.Timestamp("2026-05-27T00:00:00Z")
VALIDATION_END = pd.Timestamp("2026-07-27T00:00:00Z")
FINAL_END = pd.Timestamp("2026-09-27T00:00:00Z")


def _close_series(path: Path, name: str) -> pd.Series:
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    values = pd.to_numeric(frame["close"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=frame["timestamp"], name=name).dropna()
    if series.empty or not series.index.is_monotonic_increasing:
        raise ValueError(f"invalid or empty series: {path}")
    return series


def _complete_hourly(series: pd.Series) -> pd.Series:
    frame = series.to_frame("value")
    hourly = frame.resample("1h", label="right", closed="right").agg(
        value=("value", "last"),
        observations=("value", "count"),
    )
    return hourly.loc[hourly["observations"] == 12, "value"]


def _segment(timestamp: pd.Timestamp) -> str | None:
    if timestamp < DISCOVERY_END:
        return "discovery"
    if timestamp < VALIDATION_END:
        return "validation"
    if timestamp < FINAL_END:
        return "final_holdout"
    return None


def _summaries(
    timestamps: pd.DatetimeIndex,
    directions: pd.Series,
    returns: dict[int, pd.Series],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon, raw_returns in returns.items():
        signed = raw_returns * directions
        for segment in ("discovery", "validation", "final_holdout"):
            mask = pd.Series(
                [_segment(timestamp) == segment for timestamp in timestamps],
                index=timestamps,
            )
            values = signed.loc[mask].dropna()
            rows.append({
                "segment": segment,
                "horizon_hours": horizon,
                "signals": int(values.size),
                "win_rate_percent": (
                    float((values > 0).mean() * 100.0) if not values.empty else None
                ),
                "average_signed_return_percent": (
                    float(values.mean() * 100.0) if not values.empty else None
                ),
                "median_signed_return_percent": (
                    float(values.median() * 100.0) if not values.empty else None
                ),
            })
    return rows


def _future_returns(close: pd.Series, horizons: tuple[int, ...]) -> dict[int, pd.Series]:
    return {horizon: close.shift(-horizon).div(close).sub(1.0) for horizon in horizons}


def oi_hypotheses(price_5m: pd.Series, oi_5m: pd.Series) -> dict[str, list[dict[str, object]]]:
    price = _complete_hourly(price_5m).rename("price")
    oi = _complete_hourly(oi_5m).rename("oi")
    frame = pd.concat([price, oi], axis=1, join="inner").dropna()

    price_return = frame["price"].pct_change(fill_method=None)
    oi_return = frame["oi"].pct_change(fill_method=None)
    lookback = 30 * 24
    upper = price_return.rolling(lookback, min_periods=lookback).quantile(0.90).shift(1)
    lower = price_return.rolling(lookback, min_periods=lookback).quantile(0.10).shift(1)
    oi_mean = oi_return.rolling(lookback, min_periods=lookback).mean().shift(1)
    oi_std = oi_return.rolling(lookback, min_periods=lookback).std(ddof=0).shift(1)
    oi_zscore = oi_return.sub(oi_mean).div(oi_std.replace(0.0, np.nan))

    extreme_move = price_return.ge(upper) | price_return.le(lower)
    move_direction = pd.Series(
        np.sign(price_return),
        index=frame.index,
        dtype="float64",
    )
    future = _future_returns(frame["price"], (1, 4, 8))
    hypotheses: dict[str, tuple[pd.Series, pd.Series]] = {
        "rising_oi_momentum_confirmation": (extreme_move & oi_zscore.ge(1.0), move_direction),
        "falling_oi_liquidation_continuation": (extreme_move & oi_zscore.le(-1.0), move_direction),
        "falling_oi_exhaustion_reversal": (extreme_move & oi_zscore.le(-1.0), -move_direction),
    }
    return {
        name: _summaries(frame.index[mask], direction.loc[mask], {
            horizon: values.loc[mask] for horizon, values in future.items()
        })
        for name, (mask, direction) in hypotheses.items()
    }


def _prices_at(price: pd.Series, timestamps: pd.DatetimeIndex) -> pd.Series:
    positions = price.index.searchsorted(timestamps, side="right") - 1
    values = np.full(len(timestamps), np.nan, dtype="float64")
    valid = positions >= 0
    valid_positions = positions[valid]
    matched_times = price.index[valid_positions]
    fresh = (timestamps[valid] - matched_times) <= pd.Timedelta(minutes=5)
    valid_indices = np.flatnonzero(valid)[fresh]
    values[valid_indices] = price.iloc[positions[valid_indices]].to_numpy()
    return pd.Series(values, index=timestamps)


def funding_hypothesis(
    price_5m: pd.Series,
    funding_5m: pd.Series,
) -> list[dict[str, object]]:
    changed = funding_5m.ne(funding_5m.shift(1))
    funding = funding_5m.loc[changed]
    prior_mean = funding.rolling("90D", min_periods=30).mean().shift(1)
    prior_std = funding.rolling("90D", min_periods=30).std(ddof=0).shift(1)
    zscore = funding.sub(prior_mean).div(prior_std.replace(0.0, np.nan))
    region = pd.Series(
        np.where(zscore.ge(2.0), 1.0, np.where(zscore.le(-2.0), -1.0, 0.0)),
        index=funding.index,
    )
    entries = region.ne(0.0) & region.ne(region.shift(1).fillna(0.0))
    event_times = funding.index[entries]
    directions = -region.loc[entries]
    entry_price = _prices_at(price_5m, event_times)
    future: dict[int, pd.Series] = {}
    for horizon in (4, 8, 24):
        future_time = event_times + pd.Timedelta(hours=horizon)
        exit_price = _prices_at(price_5m, future_time)
        exit_price.index = event_times
        future[horizon] = exit_price.div(entry_price).sub(1.0)
    return _summaries(event_times, directions, future)


def run(price_path: Path, oi_path: Path, funding_path: Path) -> dict[str, object]:
    price = _close_series(price_path, "price")
    oi = _close_series(oi_path, "open_interest")
    funding = _close_series(funding_path, "funding")
    results = oi_hypotheses(price, oi)
    results["extreme_funding_mean_reversion"] = funding_hypothesis(price, funding)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "method": (
            "Pre-registered market-context hypotheses. All rolling thresholds are shifted "
            "one observation and all inputs are completed candles. Results measure BTC "
            "movement before any option-cost simulation."
        ),
        "segments": {
            "discovery_end": DISCOVERY_END.isoformat(),
            "validation_end": VALIDATION_END.isoformat(),
            "final_end": FINAL_END.isoformat(),
        },
        "source_rows": {
            "price": int(price.size),
            "open_interest": int(oi.size),
            "funding": int(funding.size),
            "funding_changes": int(funding.ne(funding.shift(1)).sum()),
        },
        "hypotheses": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pre-registered BTC market-context research")
    parser.add_argument("--price", required=True, type=Path)
    parser.add_argument("--oi", required=True, type=Path)
    parser.add_argument("--funding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.price, args.oi, args.funding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report["hypotheses"], indent=2, allow_nan=False))
    print(f"Market-context report complete: {args.output.resolve()}")


if __name__ == "__main__":
    main()
