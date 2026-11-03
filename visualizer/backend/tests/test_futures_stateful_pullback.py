"""Focused stateful futures setup tests: no look-ahead, frozen price levels and risk sizing."""
import pandas as pd
import pytest
from pydantic import ValidationError

from app.models import FuturesConfig, StrategyConfig
from app.futures_setups import PullbackBreakoutPlanner, risk_sized_lots, target_at_r
from app.futures_engine import _exit_level


def _frame():
    times=pd.date_range('2026-01-01T00:05:00Z',periods=12,freq='5min')
    # 15m candle closes: 00:15, 00:30, 00:45, 01:00
    data=[]
    for i,t in enumerate(times):
        data.append({'open':100, 'close':101, 'high':102, 'low':99, 'volume':100,
                     'ema20_15m':100, 'atr14_15m':4, 'volumeSMA20_5m':50})
    frame=pd.DataFrame(data,index=times)
    # Breakout happens strictly AFTER the 00:45 confirmation.
    frame.loc[times[9],'close']=103
    frame.loc[times[9],'high']=104
    return frame


def _config(**changes):
    cfg=FuturesConfig().pullback
    cfg.enabled=True
    cfg.ema_indicator_id='ema20_15m'
    cfg.atr_indicator_id='atr14_15m'
    cfg.volume_indicator_id='volumeSMA20_5m'
    cfg.swing_lookback_bars=3
    for key,value in changes.items():setattr(cfg,key,value)
    return cfg


def test_confirmation_is_frozen_and_breakout_requires_later_bar():
    frame=_frame()
    planner=PullbackBreakoutPlanner(frame,_config(), '5m')
    found=[]
    for i,(ts,row) in enumerate(frame.iterrows()):
        events=planner.step(i,ts,row)
        if events:found.append((ts,events))
    assert len(found)==1
    ts,events=found[0]
    assert ts==frame.index[9]
    long=events['LONG']
    assert long['setup_time']==frame.index[8].isoformat()
    assert long['setup_breakout_level']==102
    assert long['stop_price']==pytest.approx(98.6)
    assert long['setup_age_bars']==1


def test_expiring_setup_does_not_signal_late():
    frame=_frame()
    planner=PullbackBreakoutPlanner(frame,_config(max_wait_bars=1),'5m')
    for i,(ts,row) in enumerate(frame.iterrows()):
        events=planner.step(i,ts,row)
        assert 'SHORT' not in events


def test_equity_sizing_rounds_down_and_accounts_for_fees():
    f=FuturesConfig()
    setup=_config(equity_risk_percent=0.5,max_lots=10000)
    lots,reason,per_lot=risk_sized_lots(100000,99700,'LONG',100,f,setup)
    assert reason==''
    assert lots>=1
    assert lots*per_lot<=0.5+1e-10
    assert (lots+1)*per_lot>0.5 or (lots+1)*f.contract_btc*100000/f.leverage>100
    assert per_lot>0.3  # includes roundtrip trading costs


def test_minimum_lot_must_not_exceed_risk_budget():
    lots,reason,_=risk_sized_lots(100000,99000,'LONG',1,FuturesConfig(),_config())
    assert lots==0
    assert reason=='RISK_BUDGET_BELOW_MIN_LOT'


def test_short_target_and_stop_are_directional():
    f=FuturesConfig(stop_loss_percent=None,take_profit_percent=None)
    target=target_at_r(100,103,'SHORT',2,0.5)
    assert target==94
    pos={'entry_price':100,'direction':'SHORT','stop_price':103,'target_price':94}
    bar=type('Bar',(),{'open':100,'high':104,'low':93})()
    assert _exit_level(pos,bar,f)==('STOP_LOSS',103)


def test_opt_in_requires_matching_indicators_and_5m():
    with pytest.raises(ValidationError,match='pullback operand'):
        StrategyConfig.model_validate({'market_type':'FUTURES','futures':{
            'stop_loss_percent':None,'take_profit_percent':None,
            'pullback':{'enabled':True}}})
    with pytest.raises(ValidationError,match='requires 5m'):
        StrategyConfig.model_validate({'market_type':'FUTURES','timeframe':'15m','futures':{
            'stop_loss_percent':None,'take_profit_percent':None,
            'pullback':{'enabled':True}}})


def test_disabled_feature_preserves_legacy_futures_defaults():
    config=StrategyConfig(market_type='FUTURES')
    assert not config.futures.pullback.enabled
    assert config.futures.stop_loss_percent==1
    assert config.futures.take_profit_percent==2
