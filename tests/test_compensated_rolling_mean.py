"""Pandas rolling(3).mean() accumulator continuity is signal-critical."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.compensated_rolling_mean import CompensatedRollingMean
from backtest.ema_vwap_research import indicators
from backtest.legacy_full_indicator_stream import iter_complete_indicator_chunks


@pytest.mark.parametrize("window", [1, 3, 7])
def test_compensated_rolling_mean_is_bit_identical_to_pandas(window):
    rng = np.random.default_rng(20261103)
    data = rng.choice(
        [-0.0, 0.0, 100.0, 100.0, -100.0, 42.5, math.nan],
        size=12000,
    ).astype(float)
    data[1000:1100] = 100.0
    data[8000:8070] = math.nan
    target = pd.Series(data).rolling(window, min_periods=window).mean()
    state = CompensatedRollingMean(window)
    actual = pd.Series([state.update(float(value)) for value in data])
    pd.testing.assert_series_equal(actual, target, check_exact=True)


def test_two_stage_stoch_smoothers_do_not_restart_between_chunks():
    rng = np.random.default_rng(26)
    raw_values = rng.choice([0.0, 25.0, 100.0, math.nan], size=11000)
    reference_k = pd.Series(raw_values).rolling(3, min_periods=3).mean()
    reference_d = reference_k.rolling(3, min_periods=3).mean()
    k_state = CompensatedRollingMean(3)
    d_state = CompensatedRollingMean(3)
    result_k: list[float] = []
    result_d: list[float] = []
    for start in range(0, len(raw_values), 512):
        for raw in raw_values[start:start + 512]:
            k = k_state.update(float(raw))
            result_k.append(k)
            result_d.append(d_state.update(k))
    pd.testing.assert_series_equal(
        pd.Series(result_k), reference_k, check_exact=True,
    )
    pd.testing.assert_series_equal(
        pd.Series(result_d), reference_d, check_exact=True,
    )
    assert (
        (pd.Series(result_d) > pd.Series(result_k))
        == (reference_d > reference_k)
    ).all()


@pytest.mark.parametrize("chunk_rows", [31, 512])
def test_stoch_rsi_strict_signal_decisions_match_full_history_across_chunks(
    tmp_path, chunk_rows,
):
    rng = np.random.default_rng(20261103)
    candle_count = 9000
    steps = rng.choice([-100., -10., 5., 40., 100.], size=candle_count)
    close = 100_000 + np.cumsum(steps)
    times = pd.date_range(
        "2026-08-20T00:00:00Z", periods=candle_count, freq="5min",
    )
    file = tmp_path / "underlying_bars.csv"
    pd.DataFrame({
        "timestamp": times,
        "open": close - 1.0,
        "high": close + 8.0,
        "low": close - 9.0,
        "close": close,
        "volume": rng.uniform(1.0, 100.0, candle_count),
    }).to_csv(file, index=False)
    reference = indicators(file)
    observed = pd.concat(iter_complete_indicator_chunks(
        file, chunk_rows=chunk_rows, max_session_rows=4096,
    ))
    assert observed.index.equals(reference.index)
    for name in (
        "direction_stoch", "direction_macd_stoch",
        "direction_stoch_momentum", "direction_macd_stoch_momentum",
        "entry_signal_stoch", "entry_signal_macd_stoch",
        "entry_signal_stoch_momentum",
        "entry_signal_macd_stoch_momentum",
    ):
        pd.testing.assert_series_equal(observed[name], reference[name])
    for name in ("stoch_rsi_k", "stoch_rsi_d"):
        pd.testing.assert_series_equal(
            observed[name], reference[name],
            check_exact=False, rtol=1e-10, atol=1e-9,
        )


def test_invalid_rolling_window_fails_closed():
    for value in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="rolling window"):
            CompensatedRollingMean(value)
