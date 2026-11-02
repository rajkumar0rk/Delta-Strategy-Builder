"""Compare chunked historical-window loading with original source loading."""
from types import SimpleNamespace
import pandas as pd
import pytest

from app.data_store import DataStore


def _source(tmp_path):
    path = tmp_path / "underlying_bars.csv"
    stamps = pd.date_range("2026-10-30T00:05:00Z", periods=800, freq="5min")
    rows = []
    for i, ts in enumerate(stamps):
        rows.append({
            "timestamp": ts.isoformat(), "open": 100+i,
            "high": 101+i, "low": 99+i, "close": 100.5+i, "volume": 5+i,
        })
    pd.DataFrame(rows).to_csv(path, index=False)
    return SimpleNamespace(id="test", bars=path)


@pytest.mark.parametrize("tf", ["5m", "10m", "15m", "30m", "1h", "1D"])
def test_chunked_range_and_vectorized_aggregation_matches_original(tmp_path, monkeypatch, tf):
    p = _source(tmp_path)
    store = DataStore()
    start, end = "2026-10-30T02:15:00Z", "2026-11-01T18:00:00Z"
    monkeypatch.setenv("STRATEGY_LAB_BAR_READ_CHUNK_ROWS", "0")
    original = store.load_bars_many([p], start, end, tf, warmup_candles=3)
    monkeypatch.setenv("STRATEGY_LAB_BAR_READ_CHUNK_ROWS", "17")
    actual = store.load_bars_many([p], start, end, tf, warmup_candles=3)
    pd.testing.assert_frame_equal(actual, original)


def test_bad_chunks_rejected(tmp_path, monkeypatch):
    p = _source(tmp_path)
    store = DataStore()
    for bad in ("-1", "wrong"):
        monkeypatch.setenv("STRATEGY_LAB_BAR_READ_CHUNK_ROWS", bad)
        with pytest.raises(ValueError, match="STRATEGY_LAB_BAR_READ_CHUNK_ROWS"):
            store.load_bars_many([p], "2026-10-30", "2026-10-31")


def test_missing_candle_and_off_grid_cannot_form_complete_htf(tmp_path, monkeypatch):
    p = _source(tmp_path)
    frame = pd.read_csv(p.bars)
    # Remove one 5m close; add off-grid 00:07 to ensure it cannot replace it.
    frame = frame[frame.timestamp != frame.iloc[1].timestamp].copy()
    extra = frame.iloc[[0]].copy()
    extra["timestamp"] = "2026-10-30T00:07:00+00:00"
    pd.concat([frame, extra]).to_csv(p.bars, index=False)
    monkeypatch.setenv("STRATEGY_LAB_BAR_READ_CHUNK_ROWS", "11")
    result = DataStore().load_bars_many([p], "2026-10-30", "2026-10-31", "10m")
    assert pd.Timestamp("2026-10-30T00:10:00Z") not in result.index
