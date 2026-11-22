"""First confirmed 1H Supertrend flip + causal 5m breakout/EMA rejection.

The protective swing stop is immediately active. The 200-point trailing stop
ratchets only after a confirmed 500-point favorable move, next-bar effective.
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
from app.supertrend_ema_touch import SupertrendEMATouchCycle

EXAMPLE=(Path(__file__).resolve().parents[1] / "examples" /
         "btc-futures-supertrend-breakout-rejection-500-200-trailing.strategy.json")


def bar(ts, *, low=1040, high=1060, opened=1050, close=1050,
        ema=1000, st_direction=-1, bullish=0, bearish=0):
    return pd.Series({
        "open":opened,"high":high,"low":low,"close":close,
        "ema20_1h":ema,
        "supertrend_1h.direction":st_direction,
        "supertrend_1h.line":1200 if st_direction==-1 else 800,
        "supertrend_1h.bullish_flip":bullish,
        "supertrend_1h.bearish_flip":bearish,
    })


def test_schema_validates_breakout_and_activated_trail():
    data=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    s=StrategyConfig.model_validate(data["strategy"])
    c=s.futures.supertrend_ema_first_touch
    assert c.enabled and c.entry_mode=="BREAKOUT_OR_REJECTION"
    assert c.breakout_lookback_bars==12
    assert c.require_ema_slope and c.swing_stop_lookback_bars==12
    assert c.exit_mode=="ACTIVATED_POINT_TRAIL"
    assert c.trailing_activation_points==500
    assert c.trailing_distance_points==200
    assert all(x.kind!="ATR" for x in s.indicators)
    assert s.futures.stop_loss_percent is None and s.futures.take_profit_percent is None
    d=s.model_dump()
    d["futures"]["supertrend_ema_first_touch"]["trailing_activation_points"]=100
    with pytest.raises(ValidationError,match="activation must exceed"):
        StrategyConfig.model_validate(d)


def test_breakout_uses_only_prior_candles_and_is_one_per_flip():
    c=SupertrendEMATouchCycle("supertrend_1h","ema20_1h",
       entry_mode="BREAKOUT",breakout_lookback_bars=12,require_ema_slope=True,
       swing_stop_lookback_bars=12)
    # All 12 prior 5m candles have lows=1040: signal candle's low below
    # this does not count unless its CLOSE also breaks below 1040.
    stamps=pd.date_range("2026-01-01T00:05:00Z",periods=12,freq="5min")
    for t in stamps:
        c.observe(t,bar(t,ema=1100))
    flip=pd.Timestamp("2026-01-01T01:00:00Z")
    assert c.observe(flip,bar(flip,ema=1000,bearish=1)) is None
    t=pd.Timestamp("2026-01-01T01:05:00Z")
    assert c.observe(t,bar(t,low=1000,close=1045)) is None
    t=pd.Timestamp("2026-01-01T01:10:00Z")
    hit=c.observe(t,bar(t,low=890,close=900))
    assert hit is not None
    assert hit["direction"]=="SHORT"
    assert hit["entry_trigger"]=="BREAKOUT"
    assert hit["setup_stop_price"]==1060
    assert c.observe(t+pd.Timedelta(minutes=5),bar(t,low=800,close=850)) is None


def test_rejection_alternative_captures_touch_without_breakout():
    c=SupertrendEMATouchCycle("supertrend_1h","ema20_1h",
       entry_mode="BREAKOUT_OR_REJECTION",breakout_lookback_bars=12,
       require_ema_slope=True,swing_stop_lookback_bars=12)
    for t in pd.date_range("2026-01-01T00:05:00Z",periods=12,freq="5min"):
        c.observe(t,bar(t,ema=1100))
    flip=pd.Timestamp("2026-01-01T01:00:00Z")
    c.observe(flip,bar(flip,ema=1000,bearish=1))
    t=pd.Timestamp("2026-01-01T01:05:00Z")
    hit=c.observe(t,bar(t,low=990,high=1050,opened=1030,close=1010))
    assert hit is None  # close above EMA, invalid for SHORT
    t=pd.Timestamp("2026-01-01T01:10:00Z")
    hit=c.observe(t,bar(t,low=995,high=1030,opened=1010,close=997))
    assert hit is not None and hit["entry_trigger"]=="EMA_REJECTION"


@pytest.mark.parametrize("direction",["LONG","SHORT"])
@pytest.mark.parametrize("scenario,expected_reason",[
    ("trail","TRAILING_STOP"),("protect","STOP_LOSS"),("flip","SUPERTREND_FLIP")
])
def test_breakout_profit_trailing_and_protective_stop(
    tmp_path,monkeypatch,direction,scenario,expected_reason
):
    import app.futures_engine as engine
    root=tmp_path/"data"/"sample"
    root.mkdir(parents=True)
    for key,path in (
        ("STRATEGY_LAB_DATA_ROOT",tmp_path/"data"),
        ("STRATEGY_LAB_RESULT_ROOT",tmp_path/"results"),
        ("STRATEGY_LAB_CACHE_ROOT",tmp_path/"cache"),
    ):
        monkeypatch.setenv(key,str(path))
    # Include the prior 00:00 completed hourly EMA sample for the slope.
    stamps=pd.date_range("2026-01-01T00:00:00Z",periods=41,freq="5min")
    records=[]
    short=direction=="SHORT"
    entry=900 if short else 1200
    for ts in stamps:
        o,h,l,c=1050,1060,1040,1050
        if ts==pd.Timestamp("2026-01-01T01:10:00Z"):
            o,h,l,c=((1050,1060,890,900) if short else
                       (1050,1210,1040,1200))
        if ts>=pd.Timestamp("2026-01-01T01:15:00Z"):
            o,h,l,c=(entry,entry+20,entry-20,entry)
        if scenario=="trail":
            if ts==pd.Timestamp("2026-01-01T01:20:00Z"):
                o,h,l,c=((900,920,300,450) if short else
                           (1200,1800,1190,1650))
            if ts==pd.Timestamp("2026-01-01T01:25:00Z"):
                o,h,l,c=((450,520,430,490) if short else
                           (1650,1670,1580,1620))
        elif scenario=="protect" and ts==pd.Timestamp("2026-01-01T01:20:00Z"):
            o,h,l,c=((entry,1080,880,entry) if short else
                       (entry,1220,1020,entry))
        records.append(dict(timestamp=ts.isoformat(),open=o,high=h,low=l,
                            close=c,volume=100))
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as out:
        writer=csv.DictWriter(out,fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    original=engine.compute_indicators
    def fake_indicator(bars,*args,**kwargs):
        frame,meta=original(bars,*args,**kwargs)
        at_flip=pd.Timestamp("2026-01-01T01:00:00Z")
        opposite=pd.Timestamp("2026-01-01T02:00:00Z")
        forward="bearish_flip" if short else "bullish_flip"
        reverse="bullish_flip" if short else "bearish_flip"
        sign=-1 if short else 1
        frame["ema20_1h"]=[(1100 if short else 900) if t<at_flip
                             else 1000 for t in frame.index]
        frame["supertrend_1h.line"]=1300 if short else 800
        frame["supertrend_1h.direction"]=[
            sign if t<opposite else -sign for t in frame.index]
        for flag in ("bullish_flip","bearish_flip"):
            frame["supertrend_1h."+flag]=[
                int((flag==forward and at_flip<=t<opposite)
                    or (flag==reverse and t>=opposite)) for t in frame.index]
        return frame,meta
    monkeypatch.setattr(engine,"compute_indicators",fake_indicator)
    payload=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    strat=StrategyConfig.model_validate(payload["strategy"])
    strat.direction_mode="PUT" if short else "CALL"
    strat.futures.leverage=1
    strat.futures.taker_fee_percent=0
    strat.futures.gst_percent=0
    strat.futures.slippage_bps=0
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start=stamps[0].isoformat(),
        end=(stamps[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=strat))
    assert result["metrics"]["trades"]==1
    trade=result["trades"][0]
    assert trade["direction"]==direction
    assert trade["exit_reason"]==expected_reason
    assert pd.Timestamp(trade["entry_time"])==pd.Timestamp("2026-01-01T01:10:00Z")
    assert trade["entry_price"]==entry
    assert trade["initial_stop_price"]==(1060 if short else 1040)
    assert trade["target_price"] is None
    if scenario=="trail":
        assert trade["stop_price"]==(500 if short else 1600)
        assert trade["exit_price"]==(500 if short else 1600)
        assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T01:25:00Z")
    if scenario=="flip":
        assert trade["stop_price"]==trade["initial_stop_price"]
        assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T02:00:00Z")
