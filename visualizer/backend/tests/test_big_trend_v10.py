import math
import pandas as pd
import pytest
from pydantic import ValidationError

from app.indicators import compute_indicators
from app.models import IndicatorInstance, Condition, RuleGroup, StrategyConfig, BigTrendScoreConfig, BigTrendScoreComponent
from app.rules import evaluate_condition
from app.engine import _big_trend_score


def trend_bars(n=240):
    idx=pd.date_range('2026-01-01T00:00:00Z', periods=n, freq='5min')
    close=pd.Series([100+i*0.5+((i%7)-3)*0.02 for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame({'open':close-0.25,'high':close+0.6,'low':close-0.7,'close':close,'volume':100.0}, index=idx)


def test_adx_dmi_has_expected_outputs_and_uptrend_direction():
    frame,meta=compute_indicators(trend_bars(),[IndicatorInstance(id='adx14',kind='ADX_DMI',params={'period':14},chart_only=False)])
    assert {'adx14.adx','adx14.plus_di','adx14.minus_di'} <= set(frame.columns)
    last=frame[['adx14.adx','adx14.plus_di','adx14.minus_di']].dropna().iloc[-1]
    assert last['adx14.adx'] > 0
    assert last['adx14.plus_di'] > last['adx14.minus_di']


def test_formula_supports_ema_distance_over_atr():
    indicators=[
        IndicatorInstance(id='ema9',kind='EMA',params={'period':9,'source':'close'},chart_only=False),
        IndicatorInstance(id='ema50',kind='EMA',params={'period':50,'source':'close'},chart_only=False),
        IndicatorInstance(id='atr14',kind='ATR',params={'period':14},chart_only=False),
        IndicatorInstance(id='strength',kind='FORMULA',params={'expression':'(ema9 - ema50) / atr14'},chart_only=False),
    ]
    frame,_=compute_indicators(trend_bars(),indicators)
    assert frame['strength'].dropna().size > 0
    last=frame.dropna(subset=['strength']).iloc[-1]
    expected=(last.ema9-last.ema50)/last.atr14
    assert last.strength == pytest.approx(expected)


def test_candle_strength_and_atr_expansion_operands():
    indicators=[
        IndicatorInstance(id='candle',kind='CANDLE_STRENGTH',params={'atr_period':14},chart_only=False),
        IndicatorInstance(id='volx',kind='ATR_EXPANSION',params={'atr_period':14,'sma_period':20,'slope_bars':5},chart_only=False),
    ]
    frame,_=compute_indicators(trend_bars(),indicators)
    assert {'candle.body_range_percent','candle.body_atr','candle.upper_wick_ratio','candle.lower_wick_ratio'} <= set(frame.columns)
    assert {'volx.atr','volx.atr_sma','volx.atr_ratio','volx.atr_slope'} <= set(frame.columns)
    assert math.isfinite(frame['volx.atr_ratio'].dropna().iloc[-1])


def test_count_cross_and_bullish_close_count_and_slope():
    idx=pd.date_range('2026-01-01', periods=8, freq='5min', tz='UTC')
    frame=pd.DataFrame({
        'a':[0,2,0,2,0,2,0,2],
        'b':[1]*8,
        'bullish_close':[1,1,0,1,1,0,1,1],
        'ema':[1,2,3,4,5,6,7,8],
    },index=idx,dtype=float)
    cross=Condition(id='x',left='a',operator='COUNT_CROSS_ABOVE_GTE',right='b',value=3,lookback_bars=7)
    bulls=Condition(id='b',left='bullish_close',operator='COUNT_TRUE_GTE',value=5,lookback_bars=7)
    slope=Condition(id='s',left='ema',operator='SLOPE_GTE',value=1.0,lookback_bars=4)
    assert evaluate_condition(frame,7,cross)['passed']
    assert evaluate_condition(frame,7,bulls)['passed']
    out=evaluate_condition(frame,7,slope)
    assert out['passed'] and out['slope_points_per_bar']==pytest.approx(1.0)


def test_big_trend_score_weighted_0_to_100():
    idx=pd.date_range('2026-01-01', periods=2, freq='5min', tz='UTC')
    frame=pd.DataFrame({'close':[10,11],'x':[1,1],'y':[0,0]},index=idx,dtype=float)
    group=RuleGroup(conditions=[
        Condition(id='trend',left='x',operator='GT',value=0),
        Condition(id='confirm',left='y',operator='GT',value=0),
    ])
    cfg=BigTrendScoreConfig(enabled=True,threshold=60,components=[BigTrendScoreComponent(condition_id='trend',weight=3),BigTrendScoreComponent(condition_id='confirm',weight=2)])
    score=_big_trend_score(frame,1,group,cfg)
    assert score['score']==pytest.approx(60.0)
    assert score['passed'] is True


def test_big_trend_score_rejects_unknown_condition_reference():
    with pytest.raises(ValidationError):
        StrategyConfig(
            call_entry=RuleGroup(conditions=[Condition(id='real',left='close',operator='GT',value=1)]),
            call_big_trend_score=BigTrendScoreConfig(enabled=True,components=[BigTrendScoreComponent(condition_id='missing',weight=1)]),
        )


def test_higher_timeframe_indicator_is_only_available_after_completed_hour():
    frame=trend_bars(36)  # three hours of 5m bars
    out,_=compute_indicators(frame,[IndicatorInstance(id='ema1h',kind='EMA',params={'period':2,'source':'close'},chart_only=False,timeframe='1h')],'5m')
    # 2-period 1h EMA cannot exist before two complete 1h candles are available.
    assert out.loc[out.index < pd.Timestamp('2026-01-01T02:00:00Z'),'ema1h'].isna().all()
    assert out.loc[out.index >= pd.Timestamp('2026-01-01T02:00:00Z'),'ema1h'].notna().any()


def test_lower_indicator_timeframe_than_strategy_is_rejected():
    with pytest.raises(ValueError):
        compute_indicators(trend_bars(60),[IndicatorInstance(id='fast',kind='EMA',params={'period':9,'source':'close'},timeframe='5m')],'10m')


def test_daily_max_trades_blocks_later_entries(tmp_path, monkeypatch):
    import csv
    from pathlib import Path
    from app.engine import run_backtest
    from app.models import BacktestRequest, EntryBehavior
    data_root=tmp_path/'data'; ds=data_root/'sample'; ds.mkdir(parents=True)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(data_root)); monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results')); monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    def write(name,fields,rows):
        with (ds/name).open('w',newline='',encoding='utf-8') as h:
            w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
    bars=[]
    for i,c in enumerate([100,101,102,103,104,105]):
        bars.append({'timestamp':f'2026-01-01T00:{i*5:02d}:00Z','open':c-.5,'high':c+1,'low':c-1,'close':c,'volume':100})
    write('underlying_bars.csv',['timestamp','open','high','low','close','volume'],bars)
    write('option_instruments.csv',['symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],[{'symbol':'BTC100CE','source_symbol':'BTC100CE','expiry':'2026-01-02','strike':100,'option_type':'CE','activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001}])
    quotes=[{'timestamp':f'2026-01-01T00:{i*5:02d}:00Z','symbol':'BTC100CE','bid':10+i,'ask':11+i,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'} for i in range(6)]
    write('option_quotes.csv',['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest','source_event'],quotes)
    entry=RuleGroup(conditions=[Condition(id='always',left='close',operator='GT',value=0)])
    strategy=StrategyConfig(direction_mode='CALL',call_entry=entry,call_entry_lifecycles=[EntryBehavior(id='life',name='life',trigger_condition_id='always',max_entries_per_activation=10)],call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='exit',left='close',operator='GTE',value=101)]))
    strategy.risk.stop_loss.mode='NONE';strategy.risk.take_profit.mode='NONE';strategy.risk.profit_protection.mode='NONE';strategy.risk.max_hold_minutes=None;strategy.risk.quantity=1;strategy.risk.max_trades_per_day=1
    strategy.option.min_dte_days=0;strategy.option.max_dte_days=3;strategy.option.max_spread_percent=30
    result=run_backtest(BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',end='2026-01-01T00:30:00Z',strategy=strategy))
    assert result['metrics']['trades']==1
    assert result['metrics']['daily_risk_blocks']>=1
