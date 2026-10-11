import csv
from pathlib import Path

from app.engine import run_backtest
from app.models import BacktestRequest, StrategyConfig, RuleGroup, Condition, EntryBehavior


def _write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as h:
        w=csv.DictWriter(h,fieldnames=fieldnames);w.writeheader();w.writerows(rows)


def _dataset(tmp_path, monkeypatch):
    data_root=tmp_path/'data';ds=data_root/'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(data_root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    closes=[100,101,102,103,104,105,106]
    bars=[]
    for i,close in enumerate(closes):
        bars.append({'timestamp':f'2026-01-01T00:{i*5:02d}:00Z','open':close-.5,'high':close+1,'low':close-1,'close':close,'volume':100})
    _write_csv(ds/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],bars)
    _write_csv(ds/'option_instruments.csv',[
        'symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'
    ],[
        {'symbol':'BTC100CE','source_symbol':'BTC100CE','expiry':'2026-01-02','strike':100,'option_type':'CE','activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001},
        {'symbol':'BTC100PE','source_symbol':'BTC100PE','expiry':'2026-01-02','strike':100,'option_type':'PE','activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001},
    ])
    quotes=[]
    for i in range(len(closes)):
        for sym in ('BTC100CE','BTC100PE'):
            px=10+i
            quotes.append({'timestamp':f'2026-01-01T00:{i*5:02d}:00Z','symbol':sym,'bid':px,'ask':px+1,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'})
    _write_csv(ds/'option_quotes.csv',['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest','source_event'],quotes)
    return ds


def test_entry_delay_and_max_buys_per_activation(tmp_path, monkeypatch):
    _dataset(tmp_path,monkeypatch)
    strategy=StrategyConfig(
        name='Lifecycle',
        call_entry=RuleGroup(conditions=[Condition(id='trend',left='close',operator='GT',value=100)]),
        put_entry=RuleGroup(conditions=[Condition(id='never',left='close',operator='LT',value=0)]),
        call_entry_behavior=EntryBehavior(trigger_condition_id='trend',delay_bars=1,max_entries_per_activation=2,cooldown_bars=0),
        call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='exit',left='close',operator='GTE',value=103)]),
    )
    strategy.risk.stop_loss.mode='NONE';strategy.risk.take_profit.mode='NONE';strategy.risk.profit_protection.mode='NONE';strategy.risk.max_hold_minutes=None
    strategy.option.min_dte_days=0;strategy.option.max_dte_days=3;strategy.option.max_spread_percent=30;strategy.risk.quantity=1
    result=run_backtest(BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',end='2026-01-01T00:35:00Z',strategy=strategy))
    assert result['metrics']['trades']==2
    assert result['trades'][0]['signal_time'].startswith('2026-01-01T00:10:00')  # one bar after 00:05 activation
    assert result['trades'][1]['signal_time'].startswith('2026-01-01T00:20:00')
    entries=[m for m in result['markers'] if m['kind']=='entry']
    assert entries[0]['details']['activation_entry_number']==1
    assert entries[1]['details']['activation_entry_number']==2


def test_exclusive_position_skips_opposite_entry_decisions_while_open(tmp_path, monkeypatch):
    _dataset(tmp_path,monkeypatch)
    strategy=StrategyConfig(
        name='Exclusive',
        call_entry=RuleGroup(conditions=[Condition(id='c',left='close',operator='GT',value=100)]),
        put_entry=RuleGroup(conditions=[Condition(id='p',left='close',operator='GT',value=100)]),
        conflict_policy='PREFER_CALL',
        call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='x',left='close',operator='GTE',value=105)]),
    )
    strategy.risk.stop_loss.mode='NONE';strategy.risk.take_profit.mode='NONE';strategy.risk.profit_protection.mode='NONE';strategy.risk.max_hold_minutes=None
    strategy.option.min_dte_days=0;strategy.option.max_dte_days=3;strategy.option.max_spread_percent=30;strategy.risk.quantity=1
    result=run_backtest(BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',end='2026-01-01T00:35:00Z',strategy=strategy))
    # A CALL opens at 00:05 and remains open through several completed candles.
    # The decision count should not contain PUT entry evaluations for those open-position candles.
    import pathlib
    rows=list(csv.DictReader(open(pathlib.Path(result['result_dir'])/'decision_events.csv',encoding='utf-8')))
    put_entries=[r for r in rows if r['kind']=='ENTRY' and r['direction']=='PUT']
    times={r['timestamp'] for r in put_entries}
    assert not any(t.startswith('2026-01-01T00:10:00') or t.startswith('2026-01-01T00:15:00') or t.startswith('2026-01-01T00:20:00') for t in times)
