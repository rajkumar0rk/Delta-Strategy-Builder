from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.data_store import DataStore
from app.engine import chart_payload
from app.indicators import _aggregate_completed, compute_indicators
from app.models import IndicatorInstance, PreviewRequest
from app.warmup import historical_bar_sources, required_warmup_candles, warmup_diagnostics


def bars(n=6000):
    index = pd.date_range("2026-01-01T00:05:00Z", periods=n, freq="5min")
    x = np.arange(n, dtype=float)
    close = 65000 + 4 * np.sin(x / 23) + .06 * x
    return pd.DataFrame({
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close, "volume": 100 + 10 * np.sin(x / 7),
    }, index=index)


@pytest.mark.parametrize("target,count", [("15m",3), ("30m",6), ("1h",12)])
def test_mtf_requires_complete_distinct_candle_closes(target, count):
    source = bars(60).iloc[:count]
    complete = _aggregate_completed(source, "5m", target)
    assert len(complete) == 1
    assert complete.index[0] == pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(target)
    # Lost source candle replaced with duplicate: count matches but HTF bar is invalid.
    bad = pd.concat([source.drop(source.index[1]), source.iloc[[0]]]).sort_index()
    assert _aggregate_completed(bad, "5m", target).empty
    off_grid = source.copy()
    shifted = list(off_grid.index)
    shifted[1] = shifted[1] + pd.Timedelta(seconds=30)
    off_grid.index = pd.DatetimeIndex(shifted)
    with pytest.raises(ValueError, match="Off-grid"):
        _aggregate_completed(off_grid, "5m", target)


@pytest.mark.parametrize("tf", ["15m", "30m", "1h"])
def test_no_htf_future_values_and_stable_completed_boundaries(tf):
    source = bars(2500)
    indicator = IndicatorInstance(id="e", kind="EMA", params={"period": 20}, timeframe=tf)
    a, _ = compute_indicators(source, [indicator], "5m")
    halfway = 1600
    altered = source.copy()
    altered.loc[altered.index[halfway + 1]:, "close"] += 100000
    b, _ = compute_indicators(altered, [indicator], "5m")
    pd.testing.assert_series_equal(a["e"].iloc[:halfway + 1], b["e"].iloc[:halfway + 1])
    # An HTF indicator can first change ONLY on the complete HTF candle close.
    changed = a["e"].ne(a["e"].shift(1)) & a["e"].notna() & a["e"].shift(1).notna()
    assert all(int(ts.minute) % int(pd.Timedelta(tf).total_seconds() // 60) == 0
               if tf != "1h" else ts.minute == 0 for ts in a.index[changed])


def test_warmup_respects_native_timeframe_and_catalog_defaults():
    inputs = [
        IndicatorInstance(id="ema50", kind="EMA", timeframe="30m", params={"period": 50}),
        IndicatorInstance(id="stoch", kind="STOCH_RSI", timeframe="15m"),
        IndicatorInstance(id="ema1h", kind="EMA", timeframe="1h", params={"period": 20}),
    ]
    requirement = required_warmup_candles(inputs, "5m")
    assert requirement >= 5 * 50 * 6
    assert requirement >= 5 * 20 * 12
    assert required_warmup_candles([], "5m") == 500


def test_warmup_never_counts_requested_first_candle():
    source = bars(1000)
    first = source.index[500]
    info = warmup_diagnostics(source, first.isoformat(), "5m", 500)
    assert info["contiguous"]
    assert info["available_candles"] == 500
    shortened = source.drop(source.index[400])
    assert not warmup_diagnostics(shortened, first.isoformat(), "5m", 500)["contiguous"]


def _write_part(folder: Path, frame: pd.DataFrame):
    folder.mkdir(parents=True, exist_ok=True)
    frame.reset_index(names="timestamp").to_csv(folder / "underlying_bars.csv", index=False)


def test_preview_uses_warmup_and_matches_long_history_indicators(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(tmp_path))
    source = bars(6000)
    _write_part(tmp_path / "sample", source)
    instances = [
        IndicatorInstance(id="ema30", kind="EMA", timeframe="30m", params={"period": 50}),
        IndicatorInstance(id="adx30", kind="ADX_DMI", timeframe="30m", params={"period": 14}),
        IndicatorInstance(id="stoch15", kind="STOCH_RSI", timeframe="15m"),
        IndicatorInstance(id="don15", kind="DONCHIAN", timeframe="15m", params={"period": 12}),
        IndicatorInstance(id="vol5", kind="VOLUME_RATIO", timeframe="5m", params={"period": 20}),
        IndicatorInstance(id="ema1h", kind="EMA", timeframe="1h", params={"period": 20}),
    ]
    start = source.index[4000]
    end = source.index[4400]
    request = PreviewRequest(dataset_id="sample", start=start.isoformat(), end=end.isoformat(),
                             timeframe="5m", indicators=instances)
    preview = chart_payload(request)
    assert preview["warmup"]["contiguous"]
    assert preview["bars"][0]["time"] == int(start.timestamp())
    assert preview["bars"][-1]["time"] == int(source.index[4399].timestamp())
    # Same indicators on entire available history: sufficiently warmed-up
    # recursive smoothers should converge within a small tolerance.
    full, _ = compute_indicators(source, instances, "5m")
    preview_map = {row["key"]: row["values"] for row in preview["series"]}
    for key in ("ema30", "adx30.adx", "stoch15.k", "stoch15.d",
                "don15.upper", "vol5", "ema1h"):
        values = {pd.Timestamp(v["time"], unit="s", tz="UTC"): v["value"]
                  for v in preview_map[key]}
        common = [ts for ts in source.index[4000:4400] if ts in values and np.isfinite(full.loc[ts, key])]
        assert common, f"No comparable indicator points for {key}"
        for ts in common:
            assert values[ts] == pytest.approx(float(full.loc[ts, key]), abs=0.003, rel=1e-7)


def test_preview_reports_missing_contiguous_history(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(tmp_path))
    frame = bars(120)
    _write_part(tmp_path / "sample", frame)
    request = PreviewRequest(dataset_id="sample", start=frame.index[40].isoformat(),
                             end=frame.index[100].isoformat(), timeframe="5m",
                             indicators=[IndicatorInstance(id="rsi",kind="RSI",params={"period":14})])
    preview = chart_payload(request)
    assert not preview["warmup"]["contiguous"]
    assert preview["warmup"]["available_candles"] == 40
