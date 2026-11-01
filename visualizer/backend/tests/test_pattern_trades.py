import pandas as pd
import pytest
from pydantic import ValidationError

from app.models import PatternTradeConfig,StrategyConfig,RuleGroup,Condition
from app.pattern_trades import _detect,PatternTracker,PatternEvent,levels


def candles(n=48):
    idx=pd.date_range("2026-11-01T00:05:00Z",periods=n,freq="5min")
    bars=pd.DataFrame({"open":[100.]*n,"high":[101.]*n,"low":[99.]*n,
                       "close":[100.]*n,"volume":[10.]*n},index=idx)
    # The 15m candle ending 00:15 is bullish marubozu.
    for i in (0,1,2):
        bars.iloc[i,bars.columns.get_loc("open")]=100+i*3
        bars.iloc[i,bars.columns.get_loc("high")]=103+i*3
        bars.iloc[i,bars.columns.get_loc("low")]=100+i*3
        bars.iloc[i,bars.columns.get_loc("close")]=103+i*3
    # Each following 5m candle meets body/volume requirements.
    for i in range(3,10):
        bars.iloc[i]=[110,113,110,113,20]
    return bars


def test_pattern_detection_on_completed_candles():
    bar=pd.DataFrame([{"open":100,"high":110,"low":100,"close":110,"volume":1}])
    assert ("BULL_MARUBOZU","CALL",1) in _detect(bar)


def test_six_subsequent_5m_candles_and_no_future_leakage():
    frame=candles()
    cfg=PatternTradeConfig(breakout_patterns=["BULL_MARUBOZU"],
         min_body_range_ratio=.6,volume_lookback_bars=2,min_volume_ratio=1)
    tracker=PatternTracker(frame,cfg)
    # First 15m pattern becomes visible only at its completed close.
    assert not tracker.at_close(1,"CALL",{"BREAKOUT":True})
    assert tracker.at_close(2,"CALL",{"BREAKOUT":True}) is None
    confirmed=tracker.at_close(3,"CALL",{"BREAKOUT":True})
    assert confirmed is not None and confirmed.formed_at==frame.index[2]
    assert confirmed.high==109 and confirmed.low==100
    tracker.consume(confirmed)
    assert tracker.at_close(4,"CALL",{"BREAKOUT":True}) is None


def test_level_geometry_and_explicit_risk():
    event=PatternEvent("x","CALL","HAMMER","PULLBACK",pd.Timestamp("2026-11-01T00:15:00Z"),110.,100.)
    result=levels(event,112.,2.,2.,3.)
    assert result["stop"]==98.
    assert result["target_1"]==140.
    assert result["target_2"]==154.
    with pytest.raises(ValueError,match="INVALID_PATTERN_STOP_DISTANCE"):
        levels(event,95.,2.,2.,3.)


def test_pattern_opt_in_validation_prevents_silent_unsupported_execution():
    with pytest.raises(ValidationError,match="delta"):
        PatternTradeConfig(enabled=True)
    rule=RuleGroup(conditions=[Condition(left="close",operator="GT",value=100)])
    config=PatternTradeConfig(enabled=True,option_delta_assumption=.5,
         call_pullback=rule,call_breakout=rule,put_pullback=rule,put_breakout=rule)
    with pytest.raises(ValidationError,match="5m"):
        StrategyConfig(pattern_trade=config,timeframe="15m")
    with pytest.raises(ValidationError,match="BUY options only"):
        StrategyConfig(pattern_trade=config,call_action="SELL")
