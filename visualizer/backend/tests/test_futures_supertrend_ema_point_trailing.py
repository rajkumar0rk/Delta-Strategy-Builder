"""Regression tests for 1H Supertrend first EMA touch + 200-point trailing stop.

The 5m candle that FIRST touches EMA20 signals only at its close. A pending
entry fills at the NEXT 5m open. The trailing stop is active immediately,
but subsequent ratchets are effective only on the following 5m candle.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.models import BacktestRequest, StrategyConfig

EXAMPLE=(Path(__file__).resolve().parents[1] / "examples" /
         "btc-futures-supertrend-first-ema20-touch-point200-trailing.strategy.json")


def test_point200_example_is_importable_without_atr_or_fixed_tp():
    data=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    s=StrategyConfig.model_validate(data["strategy"])
    mode=s.futures.supertrend_ema_first_touch
    assert mode.enabled
    assert mode.exit_mode=="POINT_TRAIL"
    assert mode.trailing_distance_points==200
    assert s.timeframe=="5m"
    assert len(s.indicators)==2
    assert {x.kind for x in s.indicators}=={"SUPERTREND","EMA"}
    assert s.futures.stop_loss_percent is None
    assert s.futures.take_profit_percent is None
    assert "reward_r_multiple" not in data["strategy"]["futures"]["supertrend_ema_first_touch"]
    assert "atr_indicator_id" not in data["strategy"]["futures"]["supertrend_ema_first_touch"]
    broken=s.model_dump()
    broken["futures"]["supertrend_ema_first_touch"]["trailing_distance_points"]=0
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(broken)


@pytest.mark.parametrize("direction",["LONG","SHORT"])
@pytest.mark.parametrize("exit_case",["TRAILING_STOP","SUPERTREND_FLIP"])
def test_point200_trails_only_after_completed_5m_and_still_exits_on_flip(
    tmp_path,monkeypatch,direction,exit_case
):
    import app.futures_engine as engine
    root=tmp_path/"data"/"sample"
    root.mkdir(parents=True)
    for key,p in (
        ("STRATEGY_LAB_DATA_ROOT",tmp_path/"data"),
        ("STRATEGY_LAB_RESULT_ROOT",tmp_path/"results"),
        ("STRATEGY_LAB_CACHE_ROOT",tmp_path/"cache"),
    ):
        monkeypatch.setenv(key,str(p))
    dates=pd.date_range("2026-01-01T00:05:00Z",periods=40,freq="5min")
    records=[]
    for ts in dates:
        o,h,l,c=1050,1060,1040,1050
        if ts==pd.Timestamp("2026-01-01T01:10:00Z"):
            l=990  # first EMA20 touch; pending entry fills on next bar open
        if exit_case=="TRAILING_STOP":
            if ts==pd.Timestamp("2026-01-01T01:15:00Z"):
                # Its FAVORABLE extreme is seen only after old-stop testing.
                # Same-bar reversal does not magically use a newer stop.
                if direction=="LONG":o,h,l,c=1050,1450,1040,1400
                else:o,h,l,c=1050,1060,650,700
            if ts==pd.Timestamp("2026-01-01T01:20:00Z"):
                # The stop tightened at 01:15 is now effective.
                if direction=="LONG":o,h,l,c=1400,1460,1200,1300
                else:o,h,l,c=700,900,640,850
        records.append(dict(timestamp=ts.isoformat(),open=o,high=h,
                            low=l,close=c,volume=100))
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as out:
        w=csv.DictWriter(out,fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)

    actual=engine.compute_indicators
    def fake_confirmed_hour(bars,*args,**kwargs):
        frame,meta=actual(bars,*args,**kwargs)
        flip=pd.Timestamp("2026-01-01T01:00:00Z")
        opposite=pd.Timestamp("2026-01-01T02:00:00Z")
        first="bullish_flip" if direction=="LONG" else "bearish_flip"
        reverse="bearish_flip" if direction=="LONG" else "bullish_flip"
        frame["supertrend_1h.line"]=980 if direction=="LONG" else 1150
        frame["supertrend_1h.direction"]=[
            (1 if direction=="LONG" else -1) if ts<opposite else
            (-1 if direction=="LONG" else 1) for ts in frame.index]
        for flag in ("bullish_flip","bearish_flip"):
            frame["supertrend_1h."+flag]=[
                int((flag==first and flip<=ts<opposite)
                    or (flag==reverse and ts>=opposite)) for ts in frame.index]
        frame["ema20_1h"]=1000
        return frame,meta
    monkeypatch.setattr(engine,"compute_indicators",fake_confirmed_hour)

    d=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    s=StrategyConfig.model_validate(d["strategy"])
    s.direction_mode="CALL" if direction=="LONG" else "PUT"
    s.futures.leverage=1  # keep synthetic candle moves separate from margin breach
    s.futures.slippage_bps=0
    s.futures.taker_fee_percent=0
    s.futures.gst_percent=0
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start=dates[0].isoformat(),end=(dates[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=s))
    assert result["metrics"]["trades"]==1
    trade=result["trades"][0]
    assert trade["direction"]==direction
    assert pd.Timestamp(trade["entry_time"])==pd.Timestamp("2026-01-01T01:10:00Z")
    assert trade["entry_price"]==1050
    assert trade["initial_stop_price"]==(850 if direction=="LONG" else 1250)
    assert trade["target_price"] is None
    assert trade["reference_r_points"] is None
    assert trade["exit_reason"]==exit_case
    if exit_case=="TRAILING_STOP":
        assert trade["stop_price"]==(1250 if direction=="LONG" else 850)
        assert trade["exit_price"]==(1250 if direction=="LONG" else 850)
        assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T01:20:00Z")
    else:
        assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T02:00:00Z")
        assert trade["stop_price"] is not None
    assert result["futures_research"]["supertrend_ema_first_touch"]["exit_mode"]=="POINT_TRAIL"
