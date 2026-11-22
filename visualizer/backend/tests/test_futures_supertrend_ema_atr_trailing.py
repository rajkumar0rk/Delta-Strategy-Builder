"""1H Supertrend-first EMA20 touch with no TP and a causal 3xATR(14) trailing stop."""
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
         "btc-futures-supertrend-first-ema20-touch-atr3-trailing.strategy.json")


def test_first_touch_atr_trailing_import_and_backward_compatible_defaults():
    payload=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    strategy=StrategyConfig.model_validate(payload["strategy"])
    config=strategy.futures.supertrend_ema_first_touch
    assert config.enabled and config.exit_mode=="ATR_TRAIL"
    assert config.atr_indicator_id=="atr14_1h"
    assert config.trailing_atr_multiple==3
    assert "reward_r_multiple" not in payload["strategy"]["futures"]["supertrend_ema_first_touch"]
    assert strategy.futures.take_profit_percent is None
    assert strategy.futures.stop_loss_percent is None
    assert strategy.indicators[-1].kind=="ATR"
    assert strategy.indicators[-1].timeframe=="1h"
    original=StrategyConfig.model_validate({
        "market_type":"FUTURES","timeframe":"5m"
    })
    assert original.futures.supertrend_ema_first_touch.exit_mode=="REFERENCE_2R"
    altered=strategy.model_dump()
    altered["indicators"]=[x for x in altered["indicators"] if x["kind"]!="ATR"]
    with pytest.raises(ValidationError,match="1h ATR"):
        StrategyConfig.model_validate(altered)


@pytest.mark.parametrize("direction",["LONG","SHORT"])
def test_3x_atr_stop_starts_at_entry_and_ratchets_after_prior_candle(
    tmp_path,monkeypatch,direction
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
        o,h,l,c=105,106,104,105
        if ts==pd.Timestamp("2026-01-01T01:05:00Z"):
            l=99  # first EMA20 touch; no entry until 01:10 OPEN
        if ts==pd.Timestamp("2026-01-01T01:15:00Z"):
            if direction=="LONG":o,h,l,c=105,130,104,120
            else:o,h,l,c=105,106,80,90
        if ts==pd.Timestamp("2026-01-01T01:20:00Z"):
            if direction=="LONG":o,h,l,c=120,121,113,119
            else:o,h,l,c=90,97,85,91
        records.append(dict(timestamp=ts.isoformat(),open=o,high=h,low=l,close=c,volume=100))
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    actual_compute=engine.compute_indicators

    def synthetic_indicators(bars,*args,**kwargs):
        frame,meta=actual_compute(bars,*args,**kwargs)
        flip=pd.Timestamp("2026-01-01T01:00:00Z")
        label="bullish_flip" if direction=="LONG" else "bearish_flip"
        frame["supertrend_1h.line"]=98 if direction=="LONG" else 112
        frame["supertrend_1h.direction"]=1 if direction=="LONG" else -1
        frame["supertrend_1h.bullish_flip"]=[
            int(label=="bullish_flip" and flip<=ts<flip+pd.Timedelta(hours=1))
            for ts in frame.index]
        frame["supertrend_1h.bearish_flip"]=[
            int(label=="bearish_flip" and flip<=ts<flip+pd.Timedelta(hours=1))
            for ts in frame.index]
        frame["ema20_1h"]=100
        frame["atr14_1h"]=5.0   # last confirmed 1h ATR at every 5m close
        return frame,meta
    monkeypatch.setattr(engine,"compute_indicators",synthetic_indicators)
    payload=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    strategy=StrategyConfig.model_validate(payload["strategy"])
    strategy.direction_mode="CALL" if direction=="LONG" else "PUT"
    strategy.futures.slippage_bps=0
    strategy.futures.taker_fee_percent=0
    strategy.futures.gst_percent=0

    result=run_backtest(BacktestRequest(dataset_id="sample",
        start=dates[0].isoformat(),end=(dates[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=strategy))
    assert result["metrics"]["trades"]==1
    trade=result["trades"][0]
    assert pd.Timestamp(trade["entry_time"])==pd.Timestamp("2026-01-01T01:10:00Z")
    assert trade["entry_price"]==105
    assert trade["initial_stop_price"]==(90 if direction=="LONG" else 120)
    assert trade["target_price"] is None
    assert trade["reference_r_points"] is None
    assert trade["exit_reason"]=="TRAILING_STOP"
    assert pd.Timestamp(trade["exit_time"])==pd.Timestamp("2026-01-01T01:20:00Z")
    assert trade["stop_price"]==(115 if direction=="LONG" else 95)
    assert trade["exit_price"]==(115 if direction=="LONG" else 95)
    # No second EMA touch during the same Supertrend direction.
    assert result["futures_research"]["supertrend_ema_first_touch"]["exit_mode"]=="ATR_TRAIL"
    assert result["metrics"]["trades"]==1


def test_no_fixed_tp_while_first_touch_trail_is_enabled():
    payload=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    cfg=StrategyConfig.model_validate(payload["strategy"])
    assert cfg.futures.take_profit_percent is None
    assert cfg.futures.supertrend_ema_first_touch.exit_mode=="ATR_TRAIL"
    assert cfg.futures.supertrend_ema_first_touch.trailing_atr_multiple==3
