import csv, math
from pathlib import Path
from app.engine import run_backtest, _delta_fee
from app.models import BacktestRequest, StrategyConfig, RuleGroup, Condition


def _write_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)


def _dataset(tmp_path, monkeypatch):
    data=tmp_path/'data'; ds=data/'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(data));monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    _write_csv(ds/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],[
        {'timestamp':'2026-01-01T00:00:00Z','open':100000,'high':100100,'low':99900,'close':100000,'volume':100},
        {'timestamp':'2026-01-01T00:05:00Z','open':100000,'high':100200,'low':99950,'close':100100,'volume':100},
        {'timestamp':'2026-01-01T00:10:00Z','open':100100,'high':100300,'low':100000,'close':100200,'volume':100},
    ])
    _write_csv(ds/'option_instruments.csv',['symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],[
        {'symbol':'BTC100000CE','source_symbol':'BTC100000CE','expiry':'2026-01-02','strike':100000,'option_type':'CE','activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001},
    ])
    _write_csv(ds/'option_quotes.csv',['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest','source_event'],[
        {'timestamp':'2026-01-01T00:00:00Z','symbol':'BTC100000CE','bid':499,'ask':500,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'},
        {'timestamp':'2026-01-01T00:05:00Z','symbol':'BTC100000CE','bid':599,'ask':600,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'},
        {'timestamp':'2026-01-01T00:10:00Z','symbol':'BTC100000CE','bid':699,'ask':700,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'},
    ])


def _strategy():
    s=StrategyConfig(name='V5 fee test',call_entry=RuleGroup(conditions=[Condition(id='e',left='close',operator='GTE',value=100000)]),put_entry=RuleGroup(conditions=[Condition(id='p',left='close',operator='LT',value=0)]),call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='x',left='close',operator='GTE',value=100100)]))
    s.risk.stop_loss.mode='NONE';s.risk.take_profit.mode='NONE';s.risk.profit_protection.mode='NONE';s.risk.max_hold_minutes=None;s.risk.quantity=10;s.option.min_dte_days=0;s.option.max_dte_days=3;s.option.max_spread_percent=20
    return s


def test_delta_fee_formula_exact():
    s=_strategy()
    x=_delta_fee(100000,500,10,0.001,s.execution)
    # Notional = 100000*10*.001*.0001 = .1; cap=500*10*.001*.035=.175 -> base=.1
    assert math.isclose(x['notional_fee_usd'],0.1)
    assert math.isclose(x['premium_cap_usd'],0.175)
    assert math.isclose(x['base_fee_usd'],0.1)
    assert math.isclose(x['gst_usd'],0.018)
    assert math.isclose(x['total_fee_usd'],0.118)


def test_trade_net_uses_entry_exit_fee_and_gst_and_cache(tmp_path, monkeypatch):
    _dataset(tmp_path,monkeypatch);s=_strategy();req=BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',end='2026-01-01T00:15:00Z',strategy=s)
    r=run_backtest(req)
    assert r['metrics']['trades']==1
    t=r['trades'][0]
    assert t['entry_fee_usd']>0 and t['exit_fee_usd']>0 and t['gst_usd']>0
    assert math.isclose(t['net_pnl_usd'],t['gross_pnl_usd']-t['entry_fee_usd']-t['exit_fee_usd'],rel_tol=1e-12)
    assert len(r['equity_curve'])==2
    r2=run_backtest(req)
    assert r2['cache_hit'] is True
    assert r2['run_id']==r['run_id']
