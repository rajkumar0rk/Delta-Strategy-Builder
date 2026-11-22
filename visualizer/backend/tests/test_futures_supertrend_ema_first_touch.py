"""Regression: confirmed 1h Supertrend flip -> first EMA20 touch on 5m."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.futures_engine import _exit_level
from app.models import BacktestRequest, FuturesConfig, StrategyConfig
from app.supertrend_ema_touch import SupertrendEMATouchCycle

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-supertrend-first-ema20-touch-2r.strategy.json"


def _bar(*, low=105, high=106, ema=100, line=98, up=0, down=0, direction=1):
    return pd.Series({
        "low":low, "high":high, "ema20_1h":ema,
        "supertrend_1h.line":line, "supertrend_1h.direction":direction,
        "supertrend_1h.bullish_flip":up,
        "supertrend_1h.bearish_flip":down,
    })


def test_first_touch_is_consumed_only_once_after_confirmed_flip():
    state=SupertrendEMATouchCycle("supertrend_1h","ema20_1h")
    assert state.observe(pd.Timestamp("2026-01-01T01:00:00Z"),_bar(up=1,low=99)) is None
    # Forward-filled 1h flip flag is NOT a new flip at 01:05.
    signal=state.observe(pd.Timestamp("2026-01-01T01:05:00Z"),_bar(up=1,low=99))
    assert signal["direction"]=="LONG"
    assert signal["supertrend_reference_line"]==98
    assert state.observe(pd.Timestamp("2026-01-01T01:10:00Z"),_bar(up=1,low=99)) is None
    assert state.observe(pd.Timestamp("2026-01-01T02:00:00Z"),_bar(up=0,low=99)) is None
    # A later opposite confirmed 1h flip rearms a new opposite cycle.
    assert state.observe(pd.Timestamp("2026-01-01T03:00:00Z"),
                         _bar(down=1,up=0,direction=-1,low=99)) is None
    event=state.observe(pd.Timestamp("2026-01-01T03:05:00Z"),
                        _bar(down=1,up=0,direction=-1,low=99))
    assert event["direction"]=="SHORT"
    assert state.opposite_flip_at_close(pd.Timestamp("2026-01-01T03:05:00Z"),
                                        _bar(up=1),"SHORT") is False
    assert state.opposite_flip_at_close(pd.Timestamp("2026-01-01T04:00:00Z"),
                                        _bar(up=1),"SHORT") is True


def test_reference_line_is_not_an_executable_stop():
    cfg=FuturesConfig(stop_loss_percent=None,take_profit_percent=None)
    pos={"direction":"LONG","entry_price":105,"stop_price":None,"target_price":119,
         "supertrend_reference_line":98}
    # _exit_level needs a candle OPEN as well as high/low.
    at_stop=type("Candle",(),{"open":105,"high":110,"low":90})()
    at_tp=type("Candle",(),{"open":105,"high":120,"low":90})()
    assert _exit_level(pos,at_stop,cfg) is None
    assert _exit_level(pos,at_tp,cfg)==("TAKE_PROFIT",119)


def test_schema_example_and_rejections():
    doc=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert doc["schema_version"]==15
    s=StrategyConfig.model_validate(doc["strategy"])
    assert s.market_type=="FUTURES" and s.timeframe=="5m"
    assert s.futures.supertrend_ema_first_touch.reward_r_multiple==2
    assert all(ind.timeframe=="1h" for ind in s.indicators)
    assert s.futures.stop_loss_percent is None and s.futures.take_profit_percent is None
    altered=s.model_dump()
    altered["timeframe"]="1h"
    with pytest.raises(ValidationError,match="5m strategy"):
        StrategyConfig.model_validate(altered)
    altered=s.model_dump()
    altered["futures"]["stop_loss_percent"]=1
    with pytest.raises(ValidationError,match="legacy percent"):
        StrategyConfig.model_validate(altered)
    altered=s.model_dump()
    altered["indicators"]=[ind for ind in altered["indicators"] if ind["kind"]!="EMA"]
    with pytest.raises(ValidationError,match="EMA20"):
        StrategyConfig.model_validate(altered)


@pytest.mark.parametrize("flip_exit", [False, True])
def test_end_to_end_next_open_first_touch_and_tp_or_flip(tmp_path, monkeypatch, flip_exit):
    import app.futures_engine as futures_engine
    root=tmp_path/"data"/"sample"
    root.mkdir(parents=True)
    for key, path in (
        ("STRATEGY_LAB_DATA_ROOT",tmp_path/"data"),
        ("STRATEGY_LAB_RESULT_ROOT",tmp_path/"results"),
        ("STRATEGY_LAB_CACHE_ROOT",tmp_path/"cache"),
    ):
        monkeypatch.setenv(key,str(path))
    dates=pd.date_range("2026-01-01T00:05:00Z",periods=36,freq="5min")
    records=[]
    for ts in dates:
        high=125 if ts==pd.Timestamp("2026-01-01T01:15:00Z") and not flip_exit else 106
        low=95 if ts==pd.Timestamp("2026-01-01T01:30:00Z") else (
            99 if ts.minute in (10,20) else 104)
        records.append(dict(timestamp=ts.isoformat(),open=105,high=high,
                            low=low,close=105,volume=100))
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as h:
        writer=csv.DictWriter(h,fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    original=futures_engine.compute_indicators
    def fake_confirmed_1h(bars,*args,**kwargs):
        frame,meta=original(bars,*args,**kwargs)
        # Controlled 1h CLOSED signals: do not test indicator formula here.
        flipped=pd.Timestamp("2026-01-01T01:00:00Z")
        reversed_at=pd.Timestamp("2026-01-01T02:00:00Z")
        frame["supertrend_1h.line"]=98
        frame["supertrend_1h.direction"]=[
            -1 if ts<flipped or (flip_exit and ts>=reversed_at) else 1 for ts in frame.index]
        frame["supertrend_1h.bullish_flip"]=[
            int(flipped<=ts<reversed_at) for ts in frame.index]
        frame["supertrend_1h.bearish_flip"]=[
            int(flip_exit and reversed_at<=ts<reversed_at+pd.Timedelta(hours=1))
            for ts in frame.index]
        frame["ema20_1h"]=100
        return frame,meta
    monkeypatch.setattr(futures_engine,"compute_indicators",fake_confirmed_1h)
    doc=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    s=StrategyConfig.model_validate(doc["strategy"])
    s.futures.slippage_bps=0
    s.futures.taker_fee_percent=0
    s.futures.gst_percent=0
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start=dates[0].isoformat(),
        end=(dates[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=s))
    assert result["metrics"]["trades"]==1
    t=result["trades"][0]
    assert pd.Timestamp(t["entry_time"])==pd.Timestamp("2026-01-01T01:10:00Z")
    assert t["entry_price"]==105
    assert t["stop_price"] is None
    assert t["supertrend_reference_line"]==98
    assert t["reference_r_points"]==7
    assert t["target_price"]==119
    assert t["exit_reason"]==("SUPERTREND_FLIP" if flip_exit else "TAKE_PROFIT")
    if flip_exit:
        assert pd.Timestamp(t["exit_time"])==pd.Timestamp("2026-01-01T02:00:00Z")


@pytest.mark.parametrize("direction",["LONG","SHORT"])
def test_flip_only_has_no_fixed_tp_stop_or_atr_and_waits_for_confirmed_flip(
    tmp_path, monkeypatch, direction
):
    import app.futures_engine as futures_engine
    root=tmp_path/"data"/"sample"
    root.mkdir(parents=True)
    for key,p in (
        ("STRATEGY_LAB_DATA_ROOT",tmp_path/"data"),
        ("STRATEGY_LAB_RESULT_ROOT",tmp_path/"results"),
        ("STRATEGY_LAB_CACHE_ROOT",tmp_path/"cache"),
    ):
        monkeypatch.setenv(key,str(p))
    dates=pd.date_range("2026-01-01T00:05:00Z",periods=39,freq="5min")
    records=[]
    for ts in dates:
        # Large favorable and unfavorable intrabar moves MUST NOT exit:
        # the only strategy exit is a confirmed opposite 1h Supertrend flip.
        high=200 if ts==pd.Timestamp("2026-01-01T01:15:00Z") else 106
        low=50 if ts==pd.Timestamp("2026-01-01T01:30:00Z") else 104
        if ts==pd.Timestamp("2026-01-01T01:05:00Z"):
            low=99  # first EMA20 touch
        records.append(dict(timestamp=ts.isoformat(),open=105,
                            high=high,low=low,close=105,volume=100))
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as out:
        w=csv.DictWriter(out,fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    original=futures_engine.compute_indicators
    def closed_hour_indicators(bars,*args,**kwargs):
        frame,meta=original(bars,*args,**kwargs)
        flip=pd.Timestamp("2026-01-01T01:00:00Z")
        reverse=pd.Timestamp("2026-01-01T02:00:00Z")
        forward_field="bullish_flip" if direction=="LONG" else "bearish_flip"
        reverse_field="bearish_flip" if direction=="LONG" else "bullish_flip"
        frame["supertrend_1h.line"]=98 if direction=="LONG" else 112
        frame["supertrend_1h.direction"]=[
            (1 if direction=="LONG" else -1) if ts<reverse else
            (-1 if direction=="LONG" else 1)
            for ts in frame.index]
        for name in ("bullish_flip","bearish_flip"):
            frame["supertrend_1h."+name]=[
                int((name==forward_field and flip<=ts<reverse)
                    or (name==reverse_field and reverse<=ts))
                for ts in frame.index]
        frame["ema20_1h"]=100
        return frame,meta
    monkeypatch.setattr(futures_engine,"compute_indicators",closed_hour_indicators)
    doc=json.loads((EXAMPLE.parent /
        "btc-futures-supertrend-first-ema20-touch-flip-only.strategy.json"
    ).read_text(encoding="utf-8"))
    strategy=StrategyConfig.model_validate(doc["strategy"])
    assert strategy.futures.supertrend_ema_first_touch.exit_mode=="FLIP_ONLY"
    assert len(strategy.indicators)==2
    assert all(x.kind!="ATR" for x in strategy.indicators)
    assert strategy.futures.take_profit_percent is None
    strategy.direction_mode="CALL" if direction=="LONG" else "PUT"
    strategy.futures.slippage_bps=0
    strategy.futures.taker_fee_percent=0
    strategy.futures.gst_percent=0
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start=dates[0].isoformat(),end=(dates[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=strategy))
    assert result["metrics"]["trades"]==1
    trade=result["trades"][0]
    assert trade["stop_price"] is None
    assert trade["target_price"] is None
    assert trade["reference_r_points"] is None
    assert trade["exit_reason"]=="SUPERTREND_FLIP"
    assert pd.Timestamp(trade["entry_time"])==pd.Timestamp("2026-01-01T01:05:00Z")
    assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T02:00:00Z")
