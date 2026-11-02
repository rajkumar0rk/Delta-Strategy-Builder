import numpy as np
import pandas as pd
import pytest

from backtest.ema_vwap_research import indicators


@pytest.mark.parametrize("size", [1, 7, 31, 128])
def test_chunked_core_indicators_match_legacy(tmp_path, size):
    n = 260
    rng = np.random.default_rng(12345)
    closes = 100000 + np.cumsum(rng.normal(0, 70, n))
    timestamps = pd.date_range("2026-10-30T00:05:00Z", periods=n, freq="5min")
    source = tmp_path / "bars.csv"
    pd.DataFrame({
        "timestamp": timestamps,
        "open": closes - 2,
        "high": closes + 8,
        "low": closes - 10,
        "close": closes,
        "volume": rng.uniform(1, 500, n)
    }).to_csv(source, index=False)
    old = indicators(source)
    new = indicators(source, indicator_chunk_rows=size)
    pd.testing.assert_frame_equal(new, old, rtol=1e-10, atol=1e-9)


def test_unsorted_source_fails_closed(tmp_path):
    source = tmp_path / "bars.csv"
    source.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-11-01T00:10:00Z,1,2,1,2,10\n"
        "2026-11-01T00:05:00Z,1,2,1,2,10\n"
    )
    with pytest.raises(ValueError, match="OUT_OF_ORDER"):
        indicators(source, indicator_chunk_rows=1)
