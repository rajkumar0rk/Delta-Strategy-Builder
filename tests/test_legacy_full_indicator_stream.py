"""Full H6 indicator chunks must preserve warm-up, daily VWAP and signals."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.ema_vwap_research import indicators
from backtest.legacy_full_indicator_stream import iter_complete_indicator_chunks
from backtest.legacy_indicator_stream import iter_streamed_core_chunks


def _dataset(path, *, rows=675):
    rng = np.random.default_rng(20261103)
    closes = 100000 + np.cumsum(rng.normal(0.0, 110.0, rows))
    timestamps = pd.date_range(
        "2026-10-30T12:30:00Z", periods=rows, freq="5min",
    )
    volumes = rng.uniform(0.5, 500.0, rows)
    # A missing complete candle must be dropped identically by both paths.
    volumes[78] = np.nan
    pd.DataFrame({
        "timestamp": timestamps, "open": closes - 3,
        "high": closes + 7, "low": closes - 11, "close": closes,
        "volume": volumes,
    }).to_csv(path, index=False)


@pytest.mark.parametrize("chunk_rows", [1, 7, 19, 31, 127, 400])
def test_full_indicator_chunks_match_original_through_ist_sessions(
    tmp_path, chunk_rows,
):
    source = tmp_path / "bars.csv"
    _dataset(source)
    baseline = indicators(source)
    retained = []
    parts = list(iter_complete_indicator_chunks(
        source, chunk_rows=chunk_rows,
        retention_observer=retained.append,
    ))
    result = pd.concat(parts)
    assert result.index.equals(baseline.index)
    assert result.columns.tolist() == baseline.columns.tolist()
    pd.testing.assert_frame_equal(
        result, baseline, check_exact=False, rtol=1e-10, atol=1e-9,
    )
    for name in (
        "entry_signal", "entry_signal_macd", "entry_signal_stoch",
        "entry_signal_macd_stoch", "entry_signal_stoch_momentum",
        "entry_signal_macd_stoch_momentum",
    ):
        pd.testing.assert_series_equal(result[name], baseline[name])
    assert sum(row["emitted_rows"] for row in retained) == len(baseline)
    assert max(row["context_rows"] for row in retained) <= 4096 + 20 + chunk_rows
    assert any(row["previous_context_rows"] > 0 for row in retained)


@pytest.mark.parametrize("compact", [False, True])
def test_full_indicator_chunks_match_existing_chunked_frame_and_compact_mode(
    tmp_path, compact,
):
    source = tmp_path / "bars.csv"
    _dataset(source, rows=341)
    reference = indicators(source, indicator_chunk_rows=23,
                           compact_directions=compact)
    result = pd.concat(iter_complete_indicator_chunks(
        source, chunk_rows=23, compact_directions=compact,
    ))
    pd.testing.assert_frame_equal(
        result, reference, check_exact=False, rtol=1e-10, atol=1e-9,
    )


def test_core_input_iterator_yields_without_full_history_concat(tmp_path):
    source = tmp_path / "bars.csv"
    _dataset(source, rows=34)
    parts = iter_streamed_core_chunks(source, 7)
    first = next(parts)
    assert len(first) == 7
    assert "ema9" in first and "rsi14" in first
    assert sum(len(batch) for batch in parts) == 27


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_full_indicator_chunks_reject_invalid_batch_sizes(tmp_path, bad):
    with pytest.raises(ValueError, match="chunk_rows"):
        list(iter_complete_indicator_chunks(tmp_path / "not-read.csv",
                                            chunk_rows=bad))
    with pytest.raises(ValueError, match="max_session_rows"):
        list(iter_complete_indicator_chunks(tmp_path / "not-read.csv",
                                            max_session_rows=bad))


def test_full_indicator_stream_enforces_session_cap(tmp_path):
    source = tmp_path / "bars.csv"
    _dataset(source, rows=50)
    with pytest.raises(ValueError, match="SESSION_ROW_LIMIT"):
        list(iter_complete_indicator_chunks(
            source, chunk_rows=7, max_session_rows=12,
        ))


def test_full_indicator_stream_rejects_unsorted_timestamps(tmp_path):
    source = tmp_path / "bars.csv"
    source.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-11-01T00:10:00Z,1,2,1,2,10\n"
        "2026-11-01T00:05:00Z,1,2,1,2,10\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="OUT_OF_ORDER"):
        list(iter_complete_indicator_chunks(source, chunk_rows=1))
