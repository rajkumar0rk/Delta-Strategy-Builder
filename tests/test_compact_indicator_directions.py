"""Categorical direction columns retain exact signal values and types elsewhere."""
import numpy as np
import pandas as pd
import pytest

from backtest.ema_vwap_research import indicators


DIRECTIONS = (
    "direction",
    "direction_macd",
    "direction_stoch",
    "direction_macd_stoch",
    "direction_stoch_momentum",
    "direction_macd_stoch_momentum",
)


@pytest.mark.parametrize("chunks", [None, 1, 17, 64])
def test_compact_direction_parity_and_memory(tmp_path, chunks):
    n = 290
    rng = np.random.default_rng(20261102)
    close = 100_000 + np.cumsum(rng.normal(0, 135, n))
    times = pd.date_range("2026-10-30T00:00:00Z", periods=n, freq="5min")
    source = tmp_path / "bars.csv"
    pd.DataFrame({
        "timestamp": times,
        "open": close - 1.5,
        "high": close + 8,
        "low": close - 10,
        "close": close,
        "volume": rng.uniform(1, 400, n),
    }).to_csv(source, index=False)
    kwargs = {} if chunks is None else {"indicator_chunk_rows": chunks}
    reference = indicators(source, **kwargs)
    compact = indicators(source, compact_directions=True, **kwargs)

    assert compact.index.equals(reference.index)
    assert list(compact.columns) == list(reference.columns)
    for name in DIRECTIONS:
        assert isinstance(compact[name].dtype, pd.CategoricalDtype)
        assert list(compact[name].cat.categories) == ["", "CALL", "PUT"]
        assert compact[name].astype(str).tolist() == reference[name].tolist()
    pd.testing.assert_frame_equal(
        compact.astype({name: "object" for name in DIRECTIONS}),
        reference,
        check_exact=True,
    )
    assert int(compact.memory_usage(index=True, deep=True).sum()) < int(
        reference.memory_usage(index=True, deep=True).sum()
    )


def test_compact_indicator_default_is_disabled():
    from inspect import signature
    from backtest.ema_vwap_research import run_dataset

    assert signature(indicators).parameters["compact_directions"].default is False
    assert signature(run_dataset).parameters[
        "compact_indicator_directions"
    ].default is False
