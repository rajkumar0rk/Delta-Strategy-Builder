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


def test_end_to_end_frozen_setup_risk_sized_entry_and_close(tmp_path,monkeypatch):
    import csv
    from app.models import BacktestRequest
    from app.engine import run_backtest
    root=tmp_path/'data'
    root.mkdir()
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    times=pd.date_range('2026-01-01T00:05:00Z',periods=90,freq='5min')
    values=[]
    for i,t in enumerate(times):
        candle={'timestamp':t.isoformat(),'open':100,'high':102,'low':99,'close':101,'volume':100}
        if i in (60,61,62):
            candle.update(high=103,low=99,close=102)
        elif i==63:
            candle.update(high=105,low=99,close=104,volume=300)
        elif i==64:
            candle.update(open=104,high=120,low=104,close=115)
        values.append(candle)
    source=root/'sample'
    source.mkdir()
    with (source/'underlying_bars.csv').open('w',newline='') as fh:
        writer=csv.DictWriter(fh,fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
    spec={
        'market_type':'FUTURES','direction_mode':'CALL','timeframe':'5m',
        'indicators':[
            {'id':'ema20_15m','kind':'EMA','timeframe':'15m','params':{'period':20}},
            {'id':'atr14_15m','kind':'ATR','timeframe':'15m','params':{'period':14}},
            {'id':'volumeSMA20_5m','kind':'VOLUME_SMA','timeframe':'5m','params':{'period':20}},
        ],
        'call_entry':{'conditions':[{'id':'trend','left':'close','operator':'GT','value':0}]},
        'futures':{
            'funding_mode':'EXCLUDE_WITH_WARNING','stop_loss_percent':None,
            'take_profit_percent':None,'pullback':{'enabled':True,'swing_lookback_bars':3,
               'equity_risk_percent':0.5}},
        'risk':{'starting_balance_usd':100,'max_hold_minutes':120}
    }
    strategy=StrategyConfig.model_validate(spec)
    response=run_backtest(BacktestRequest(
        dataset_id='sample',start=times[0].isoformat(),
        end=(times[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=strategy))
    assert response['metrics']['trades']>=1, response['metrics']
    trade=response['trades'][0]
    assert trade['entry_lifecycle_id']=='PULLBACK_SETUP'
    assert trade['quantity']>0
    assert trade['stop_price']<trade['entry_price']<trade['target_price']
    # Next 5m OPEN equals previous signal candle CLOSE in timestamp convention.
    assert trade['entry_time']==trade['entry_lifecycle_signal_time']
    assert trade['net_pnl_usd']==pytest.approx(
        trade['gross_pnl_usd']-trade['fees_usd']+trade['funding_usd'])
    assert response['metrics']['cash_reconciliation_residual_usd']==pytest.approx(0)
