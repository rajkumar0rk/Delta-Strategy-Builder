import numpy as np
import pandas as pd
import pytest
from backtest import positional_bar_windows as windows


@pytest.mark.parametrize("duplicate", [False, True])
def test_windows_preserve_legacy_rows(duplicate):
    idx = pd.date_range("2026-09-01", periods=12, freq="5min", tz="UTC")
    if duplicate:
        idx = idx.insert(4, idx[4])
    frame = pd.DataFrame({"close": np.arange(len(idx), dtype=float),
                          "high": np.arange(len(idx), dtype=float)+2,
                          "low": np.arange(len(idx), dtype=float)-2}, index=idx)
    frame.iloc[2, 0] = np.nan
    for cutoff in [idx[0] - pd.Timedelta(minutes=1), idx[4], idx[-1] + pd.Timedelta(minutes=10)]:
        pd.testing.assert_frame_equal(windows.completed_window(frame, cutoff), frame.loc[:cutoff])
        expected = frame.loc[:cutoff, "close"].dropna()
        assert windows.latest_completed_close(frame, cutoff, -5.0) == (
            float(expected.iloc[-1]) if not expected.empty else -5.0)
        for direction in ("CALL","PUT"):
            previous = frame.loc[frame.index < cutoff].tail(4)
            result = float(previous["low"].min() if direction=="CALL" else previous["high"].max()) if not previous.empty else np.nan
            actual = windows.previous_structure_level(frame,cutoff,4,direction)
            assert (np.isnan(result) and np.isnan(actual)) or actual==result
        for end in [cutoff,idx[-1]+pd.Timedelta(minutes=1)]:
            pd.testing.assert_frame_equal(
                windows.post_entry_window(frame,cutoff,end),
                frame.loc[(frame.index>cutoff)&(frame.index<=end)])
