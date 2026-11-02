"""Simulation-frame reduction preserves all candles used by trade replay."""
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.ema_vwap_research import EarlyFailureConfig
from backtest.simulation_frame_retention import prepare_simulation_frame


REQUIRED = (
    "open", "high", "low", "close", "volume", "ema9", "ema20",
    "ema50", "vwap", "rsi14", "atr14", "volume_median20_prior",
    "macd", "macd_signal", "stoch_rsi_k", "direction",
)


def _frame(count=28):
    idx=pd.date_range("2026-09-01",periods=count,freq="5min",tz="UTC")
    return pd.DataFrame({
        name: ([float(x) for x in range(count)]
               if name not in {"direction"} else ["CALL"]*count)
        for name in REQUIRED
    }, index=idx)


def _scenario(structure, confirmation):
    return SimpleNamespace(
        early_failure=EarlyFailureConfig(structure_lookback_candles=structure),
        directional_confirmation_minutes=confirmation,
    )


def test_retains_longest_prior_lookback_and_all_forward_candles():
    frame=_frame()
    signal=SimpleNamespace(timestamp_ns=frame.index[12].value)
    extra=SimpleNamespace(timestamp_ns=frame.index[18].value)
    scenarios=[_scenario(5,10),_scenario(3,40)]
    projected=prepare_simulation_frame(
        frame, {"a":[signal],"b":[extra]}, scenarios,
    )
    # 40m confirmation = eight bars plus signal candle; keep nine previous.
    assert len(projected)==len(frame)-3
    assert projected.index[0]==frame.index[3]
    assert projected.index[-1]==frame.index[-1]
    assert "open" not in projected.columns
    assert "stoch_rsi_k" not in projected.columns
    assert "direction" not in projected.columns
    assert "close" in projected.columns
    assert "macd_signal" in projected.columns
    assert projected["close"].iloc[9]==frame["close"].iloc[12]
    assert projected["close"].to_numpy().base is not frame["close"].to_numpy().base


def test_keeps_exact_structure_lookback_even_when_disabled():
    frame=_frame()
    signal=SimpleNamespace(timestamp_ns=frame.index[14].value)
    result=prepare_simulation_frame(
        frame, {"single":[signal]}, [_scenario(10,0)],
    )
    assert result.index[0]==frame.index[4]
    assert result.loc[:frame.index[14], "low"].iloc[:-1].tail(10).tolist()==frame["low"].iloc[4:14].tolist()


def test_duplicate_timestamps_maintain_all_preceding_rows():
    frame=_frame()
    frame= pd.concat([frame.iloc[:12], frame.iloc[11:12], frame.iloc[12:]])
    signal=SimpleNamespace(timestamp_ns=frame.index[13].value)
    result=prepare_simulation_frame(frame, {"a":[signal]},[_scenario(4,0)])
    assert result.index[-1]==frame.index[-1]
    assert result.index[0]==frame.index[9]
    assert result.index.is_monotonic_increasing


def test_no_events_missing_columns_and_unsorted_fall_back_without_guessing():
    frame=_frame()
    assert prepare_simulation_frame(frame,{"none":[]},[_scenario(4,0)]) is frame
    missing=frame[["close"]]
    assert prepare_simulation_frame(missing,{"a":[SimpleNamespace(timestamp_ns=frame.index[12].value)]},[_scenario(4,0)]) is missing
    unordered=frame.iloc[::-1]
    assert prepare_simulation_frame(unordered,{"a":[SimpleNamespace(timestamp_ns=frame.index[12].value)]},[_scenario(4,0)]) is unordered
