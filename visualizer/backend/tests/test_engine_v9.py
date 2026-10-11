import csv
from pathlib import Path
import pytest

from app.engine import run_backtest
from app.data_store import DataStore
from app.models import BacktestRequest, StrategyConfig, RuleGroup, Condition, EntryBehavior


def _write(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as h:
        w=csv.DictWriter(h, fieldnames=fields); w.writeheader(); w.writerows(rows)


def _dataset(root: Path, name: str, start_minute: int, closes, include_put=True):
    ds=root/name
    bars=[]
    for j,close in enumerate(closes):
        minute=start_minute+j*5
        hour=minute//60; mm=minute%60
        bars.append({'timestamp':f'2026-01-01T{hour:02d}:{mm:02d}:00Z','open':close,'high':close+1,'low':close-1,'close':close,'volume':100})
    _write(ds/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],bars)
    inst=[]
    for typ in (['CE','PE'] if include_put else ['CE']):
        sym=f'BTC100{typ}'
        inst.append({'symbol':sym,'source_symbol':sym,'expiry':'2026-01-02','strike':100,'option_type':typ,'activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001})
    _write(ds/'option_instruments.csv',['symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],inst)
    quotes=[]
    for j,_ in enumerate(closes):
        minute=start_minute+j*5; hour=minute//60; mm=minute%60
        # CALL bid rises 10->..., ask=bid+1; PUT same for completeness
        for typ in (['CE','PE'] if include_put else ['CE']):
            bid=10+j
            quotes.append({'timestamp':f'2026-01-01T{hour:02d}:{mm:02d}:00Z','symbol':f'BTC100{typ}','bid':bid,'ask':bid+1,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'})
    _write(ds/'option_quotes.csv',['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest','source_event'],quotes)
    return ds


def _strategy():
    s=StrategyConfig(
        name='v9', direction_mode='CALL', call_action='SELL',
        call_entry=RuleGroup(conditions=[Condition(id='go',left='close',operator='GTE',value=100)]),
        put_entry=RuleGroup(),
        call_entry_lifecycles=[EntryBehavior(id='call-only',name='CALL only')],
        put_entry_lifecycles=[],
        call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='exit',left='close',operator='GTE',value=102)]),
    )
    s.risk.stop_loss.mode='NONE';s.risk.take_profit.mode='NONE';s.risk.profit_protection.mode='NONE';s.risk.max_hold_minutes=None
    s.option.min_dte_days=0;s.option.max_dte_days=3;s.option.max_spread_percent=30;s.risk.quantity=1
    return s


def test_call_only_does_not_require_put_lifecycle():
    s=_strategy()
    assert s.direction_mode=='CALL'
    # Legacy migration may keep a dormant PUT lifecycle, but it is not required or evaluated.
    assert s.direction_mode=='CALL'


def test_sell_call_uses_bid_entry_and_ask_exit(tmp_path, monkeypatch):
    root=tmp_path/'data'; _dataset(root,'m1',0,[100,101,102])
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root));monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    r=run_backtest(BacktestRequest(dataset_id='m1',start='2026-01-01T00:00:00Z',end='2026-01-01T00:15:00Z',strategy=_strategy()))
    assert len(r['trades'])==1
    t=r['trades'][0]
    assert t['action']=='SELL'
    assert t['entry_execution_side']=='BID'
    assert t['exit_execution_side']=='ASK'
    assert t['entry_price']==10
    # exit condition becomes true at 00:10 -> ask is 13
    assert t['exit_price']==13
    assert t['gross_pnl_usd']==pytest.approx((10-13)*1*0.001)
    assert t['net_pnl_usd'] < t['gross_pnl_usd']


def test_multi_dataset_merges_months_and_auto_selects(tmp_path, monkeypatch):
    root=tmp_path/'data'
    _dataset(root,'jan-a',0,[100,101,102])
    _dataset(root,'jan-b',15,[103,104,105])
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    store=DataStore()
    parts=store.auto_select('2026-01-01T00:00:00Z','2026-01-01T00:30:00Z')
    assert {p.id for p in parts}=={'jan-a','jan-b'}
    bars=store.load_bars_many(parts,'2026-01-01T00:00:00Z','2026-01-01T00:30:00Z','5m')
    assert len(bars)==6
    assert float(bars.iloc[-1].close)==105


def test_preflight_reports_missing_quote_index_as_warning(tmp_path, monkeypatch):
    root=tmp_path/'data'; _dataset(root,'m1',0,[100,101,102],include_put=False)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    store=DataStore(); parts=[store.resolve('m1')]
    rep=store.preflight(parts,'2026-01-01T00:00:00Z','2026-01-01T00:15:00Z',_strategy())
    assert rep['ok'] is True
    assert any('one-time SQLite index' in x for x in rep['warnings'])


def test_10m_aggregation_uses_utc_clock_boundaries_not_dataset_anchor(tmp_path, monkeypatch):
    root=tmp_path/'data'
    # File begins at 00:00, which previously shifted every 10m group by 5 minutes.
    _dataset(root,'m1',0,[100,101,102,103,104,105])
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    store=DataStore(); parts=[store.resolve('m1')]
    bars=store.load_bars_many(parts,'2026-01-01T00:10:00Z','2026-01-01T00:30:00Z','10m')
    # 00:05+00:10 => 00:10, 00:15+00:20 => 00:20
    assert list(bars.index.strftime('%H:%M')) == ['00:10','00:20']
    assert float(bars.iloc[0].open)==101
    assert float(bars.iloc[0].close)==102


def test_10m_aggregation_across_datasets_with_different_start_phase(tmp_path, monkeypatch):
    root=tmp_path/'data'
    _dataset(root,'a',0,[100,101,102])       # 00:00, 00:05, 00:10
    _dataset(root,'b',15,[103,104,105,106])  # 00:15, 00:20, 00:25, 00:30
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root));monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    store=DataStore(); parts=[store.resolve('a'),store.resolve('b')]
    bars=store.load_bars_many(parts,'2026-01-01T00:10:00Z','2026-01-01T00:31:00Z','10m')
    assert list(bars.index.strftime('%H:%M')) == ['00:10','00:20','00:30']
