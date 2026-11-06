"""Cross-market reusable pullback/stop lifecycle; options always quote-backed."""
import csv

import pandas as pd
import pytest
from pydantic import ValidationError

from app.models import StrategyConfig, BacktestRequest
from app.engine import run_backtest
from app.shared_execution import (PendingUnderlyingStop, CompletedHourlyTrendGate,
    clock_due, pending_expired, stop_trigger_price, remaining_daily_risk)


def test_market_neutral_bounded_helpers_and_clock():
    level=stop_trigger_price(102,upward=True,tick_size=.5,buffer_ticks=1)
    assert level==102.5
    assert stop_trigger_price(99,upward=False,tick_size=.5,buffer_ticks=1)==98.5
    order=PendingUnderlyingStop('CALL',pd.Timestamp('2026-01-01T08:30:00Z'),1,
                                level,98.5,102)
    row=pd.Series({'open':104,'high':105,'low':103})
    assert order.crossed(row)==104
    assert not order.expired(pd.Timestamp('2026-01-01T09:00:00Z'),7,5,6)
    assert order.expired(pd.Timestamp('2026-01-01T09:05:00Z'),8,5,6)
    assert pending_expired('2026-01-01T08:30:00Z','2026-01-01T09:05:00Z',5,6,1)
    assert clock_due(pd.Timestamp('2026-01-01T18:15:00Z'),'23:45','Asia/Kolkata')
    assert not clock_due(pd.Timestamp('2026-01-01T18:10:00Z'),'23:45','Asia/Kolkata')
    assert remaining_daily_risk(100,-.75,1)==pytest.approx(.25)


def config(**patch):
    spec={
        'name':'Opt-in options underlying breakout',
        'market_type':'OPTIONS','timeframe':'5m','direction_mode':'CALL',
        'call_action':'BUY','put_action':'BUY',
        'indicators':[
            {'id':'ema20_15m','kind':'EMA','timeframe':'15m',
             'params':{'period':20,'source':'close'}},
            {'id':'atr14_15m','kind':'ATR','timeframe':'15m',
             'params':{'period':14}},
        ],
        'call_entry':{'conditions':[{'id':'bull','left':'close',
                                     'operator':'GT','value':0}]},
        'options_pullback':{
            'enabled':True,'ema_indicator_id':'ema20_15m',
            'atr_indicator_id':'atr14_15m','require_volume':False,
            'max_wait_bars':6,'reward_r_multiple':2,'stop_buffer_atr':.1,
            'size_mode':'RISK_EQUITY','equity_risk_percent':.5,
            'max_lots':10,'underlying_tick_size':.5},
        'options_force_exit_time':'23:45',
        'risk':{'starting_balance_usd':1000,'budget_usd':100,
                'max_daily_loss_percent':1,'max_hold_minutes':None,
                'stop_loss':{'mode':'NONE','value':15},
                'take_profit':{'mode':'NONE','value':30},
                'profit_protection':{'mode':'NONE'}},
        'option':{'max_spread_percent':20,'min_dte_days':0,'max_dte_days':3},
        'session':{'timezone':'Asia/Kolkata',
                   'windows':[{'start':'14:00','end':'21:59'}]}
    }
    for k,v in patch.items():
        spec[k]=v
    return StrategyConfig.model_validate(spec)


def dataset(tmp_path,monkeypatch,*,hit_target=False,missing_quotes=False,short=False):
    for k,v in [('STRATEGY_LAB_DATA_ROOT',tmp_path/'data'),
                ('STRATEGY_LAB_RESULT_ROOT',tmp_path/'results'),
                ('STRATEGY_LAB_CACHE_ROOT',tmp_path/'cache')]:
        monkeypatch.setenv(k,str(v))
    root=tmp_path/'data'/'sample'
    root.mkdir(parents=True)
    times=pd.date_range('2026-01-01T00:05:00Z',periods=290,freq='5min')
    bars=[];quotes=[]
    for i,ts in enumerate(times):
        row={'timestamp':ts.isoformat(),'open':101 if short else 100,
             'high':102,'low':99,
             'close':(101 if i<101 else 100) if short else (100 if i<101 else 101),
             'volume':100}
        if i==102:
            if short:
                row['low']=95
            else:
                row['high']=105  # stop-market wick: close is only 101
        if hit_target and i==103:
            if short:
                row['low']=85
            else:
                row['high']=112
        bars.append(row)
        if not missing_quotes or i<101:
            quotes.append({'timestamp':ts.isoformat(),'symbol':'BTC100PE' if short else 'BTC100CE',
               'bid':10+(i>=102)*1,'ask':11+(i>=102)*1,
               'bid_size':1000,'ask_size':1000,'volume':100,'open_interest':1000,
               'source_event':'test'})
    instruments=[{'symbol':'BTC100PE' if short else 'BTC100CE',
        'source_symbol':'BTC100PE' if short else 'BTC100CE',
        'expiry':'2026-01-03','strike':100,'option_type':'PE' if short else 'CE',
        'activation':'2025-12-31T00:00:00Z',
        'expiration':'2026-01-03T00:00:00Z',
        'price_precision':2,'size_precision':0,'price_increment':.1,
        'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':.001}]
    for name,rows in [('underlying_bars.csv',bars),
                      ('option_instruments.csv',instruments),
                      ('option_quotes.csv',quotes)]:
        with (root/name).open('w',encoding='utf-8',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return times


def run(tmp_path,monkeypatch,*,hit_target=False,missing_quotes=False,short=False):
    times=dataset(tmp_path,monkeypatch,hit_target=hit_target,
                  missing_quotes=missing_quotes,short=short)
    return run_backtest(BacktestRequest(dataset_id='sample',
        start=times[0].isoformat(),
        end=(times[-1]+pd.Timedelta(minutes=5)).isoformat(),
        strategy=config(direction_mode='PUT',
            put_entry={'conditions':[{'id':'bear','left':'close',
                                     'operator':'GT','value':0}]})
            if short else config(),storage_mode='COMPACT'))


def test_option_quote_entry_and_underlying_2r_target(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,hit_target=True)
    assert result['metrics']['option_stop_order_events']['armed']>=1
    assert result['metrics']['option_stop_order_events']['triggered']>=1, (result['metrics'],[(m.get('time'),m.get('text')) for m in result['markers'] if m.get('text','').startswith('OPTION')][:20])
    assert result['metrics']['trades']>=1, (result['metrics'],[(m.get('time'),m.get('text')) for m in result['markers'] if m.get('text','').startswith('OPTION')][:20])
    first=result['trades'][0]
    assert first['action']=='BUY' and first['direction']=='CALL'
    assert first['entry_execution_side']=='ASK'
    assert first['underlying_signal_stop']<first['underlying_r_target']
    assert first['underlying_levels']['r_definition']=='BTC_UNDERLYING_POINTS_NOT_OPTION_PREMIUM'
    assert first['option_risk_per_unit_usd']>0
    assert first['exit_reason']=='UNDERLYING_R_TARGET'
    assert first['fees_usd']>0 and first['entry_price']<100


def test_missing_option_quote_never_fabricates_entry(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,missing_quotes=True)
    assert result['metrics']['trades']==0
    assert result['metrics']['option_stop_order_events']['triggered']>=1


def test_option_force_exit_is_independent_of_entry_window(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch)
    assert result['metrics']['trades']>=1
    trade=result['trades'][0]
    assert trade['exit_reason']=='OPTION_FORCE_EXIT_CLOCK'
    assert pd.Timestamp(trade['exit_time']).tz_convert('Asia/Kolkata').strftime('%H:%M')=='23:45'


def test_disabled_mode_and_sell_rejection_are_backwards_compatible():
    assert StrategyConfig().options_pullback.enabled is False
    assert StrategyConfig().options_force_exit_time is None
    with pytest.raises(ValidationError,match='BUY CALL/PUT only'):
        config(call_action='SELL')
    with pytest.raises(ValidationError,match='legacy option exits'):
        config(risk={'stop_loss':{'mode':'OPTION_PERCENT','value':15}})
    with pytest.raises(ValidationError,match='1h trend IDs'):
        config(options_pullback={'enabled':True,'trend_crossover_block_bars':3})
    with pytest.raises(ValidationError,match='options_force_exit_time'):
        config(options_force_exit_time='25:00')


def test_buy_put_uses_short_underlying_trigger_with_option_ask_and_bid(tmp_path,monkeypatch):
    result=run(tmp_path,monkeypatch,short=True,hit_target=True)
    assert result['metrics']['option_stop_order_events']['triggered']>=1
    assert result['metrics']['trades']>=1
    trade=result['trades'][0]
    assert trade['direction']=='PUT' and trade['action']=='BUY'
    assert trade['symbol']=='BTC100PE'
    assert trade['entry_execution_side']=='ASK'
    assert trade['exit_execution_side']=='BID'
    assert trade['underlying_signal_stop']>trade['underlying_r_target']
    assert trade['exit_reason']=='UNDERLYING_R_TARGET'
