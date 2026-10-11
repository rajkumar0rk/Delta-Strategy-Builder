import csv
from pathlib import Path

from app.data_store import DataStore
from app.engine import run_backtest
from app.models import BacktestRequest, Condition, EntryBehavior, RuleGroup, StrategyConfig


def _write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)


def _dataset(tmp_path, monkeypatch):
    data_root = tmp_path / 'data'; ds = data_root / 'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data_root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))
    closes = [100, 101, 102, 103, 104, 105]
    volumes = [100, 100, 100, 200, 200, 200]
    bars = []
    for i, (close, volume) in enumerate(zip(closes, volumes)):
        bars.append({'timestamp': f'2026-01-01T00:{i*5:02d}:00Z', 'open': close-.5, 'high': close+1, 'low': close-1, 'close': close, 'volume': volume})
    _write_csv(ds/'underlying_bars.csv', ['timestamp','open','high','low','close','volume'], bars)
    _write_csv(ds/'option_instruments.csv', [
        'symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'
    ], [
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


def _base_strategy(**kwargs):
    strategy = StrategyConfig(**kwargs)
    strategy.risk.stop_loss.mode='NONE'; strategy.risk.take_profit.mode='NONE'; strategy.risk.profit_protection.mode='NONE'; strategy.risk.max_hold_minutes=None
    strategy.option.min_dte_days=0; strategy.option.max_dte_days=3; strategy.option.max_spread_percent=30; strategy.risk.quantity=1
    return strategy


def test_multiple_lifecycles_and_wait_window_choose_ready_lifecycle(tmp_path, monkeypatch):
    _dataset(tmp_path, monkeypatch)
    entry = RuleGroup(conditions=[
        Condition(id='trend', left='close', operator='GT', value=100),
        Condition(id='volume-confirm', left='volume', operator='GT', value=150),
    ])
    strategy = _base_strategy(
        name='V8 multi lifecycle',
        call_entry=entry,
        put_entry=RuleGroup(conditions=[Condition(id='never',left='close',operator='LT',value=0)]),
        call_entry_lifecycles=[
            EntryBehavior(id='fast', name='Fast window', trigger_condition_id='trend', max_wait_bars=1),
            EntryBehavior(id='patient', name='Patient window', trigger_condition_id='trend', max_wait_bars=3),
        ],
        call_exit=RuleGroup(mode='ANY', conditions=[Condition(id='exit',left='close',operator='GTE',value=104)]),
    )
    result = run_backtest(BacktestRequest(dataset_id='sample', start='2026-01-01T00:00:00Z', end='2026-01-01T00:30:00Z', strategy=strategy))
    assert result['metrics']['trades'] == 1
    assert result['trades'][0]['signal_time'].startswith('2026-01-01T00:15:00')
    assert result['trades'][0]['entry_lifecycle_id'] == 'patient'
    entry_marker = next(m for m in result['markers'] if m['kind']=='entry')
    assert entry_marker['details']['entry_lifecycle_id'] == 'patient'
    assert entry_marker['details']['max_wait_bars'] == 3


def test_wait_window_expires_until_trigger_rearms(tmp_path, monkeypatch):
    _dataset(tmp_path, monkeypatch)
    strategy = _base_strategy(
        name='V8 expiry',
        call_entry=RuleGroup(conditions=[
            Condition(id='trend',left='close',operator='GT',value=100),
            Condition(id='late',left='volume',operator='GT',value=150),
        ]),
        put_entry=RuleGroup(conditions=[Condition(id='never',left='close',operator='LT',value=0)]),
        call_entry_lifecycles=[EntryBehavior(id='short',name='Short',trigger_condition_id='trend',max_wait_bars=1)],
    )
    result = run_backtest(BacktestRequest(dataset_id='sample', start='2026-01-01T00:00:00Z', end='2026-01-01T00:30:00Z', strategy=strategy))
    assert result['metrics']['trades'] == 0
    rows = list(csv.DictReader(open(Path(result['result_dir'])/'decision_events.csv', encoding='utf-8')))
    assert any(r.get('lifecycle_reason') == 'ENTRY_WAIT_WINDOW_EXPIRED' for r in rows if r['direction']=='CALL' and r['kind']=='ENTRY')


def test_10m_aggregation_uses_complete_pairs_and_last_timestamp(tmp_path, monkeypatch):
    ds = _dataset(tmp_path, monkeypatch)
    store = DataStore(); paths = store.resolve('sample')
    frame = store.load_bars(paths, '2026-01-01T00:00:00Z', '2026-01-01T00:30:00Z', '10m')
    assert list(frame.index.strftime('%H:%M')) == ['00:10','00:20']
    first = frame.iloc[0]
    assert first.open == 100.5
    assert first.high == 103
    assert first.low == 100
    assert first.close == 102
    assert first.volume == 200


def test_older_single_lifecycle_import_migrates_to_v8_list():
    strategy = StrategyConfig.model_validate({
        'name':'legacy',
        'call_entry':{'conditions':[{'id':'a','left':'close','operator':'GT','value':1}]},
        'call_entry_behavior':{'trigger_condition_id':'a','delay_bars':2,'max_entries_per_activation':3,'cooldown_bars':1},
    })
    assert len(strategy.call_entry_lifecycles) == 1
    assert strategy.call_entry_lifecycles[0].trigger_condition_id == 'a'
    assert strategy.call_entry_lifecycles[0].delay_bars == 2
    assert strategy.call_entry_lifecycles[0].max_entries_per_activation == 3


def test_10m_aggregation_handles_five_minute_close_phase(tmp_path, monkeypatch):
    data_root = tmp_path / 'data'; ds = data_root / 'phase5'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data_root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))
    bars=[]
    for i, minute in enumerate((5,10,15,20,25,30)):
        close=100+i
        bars.append({'timestamp':f'2026-01-01T00:{minute:02d}:00Z','open':close-.5,'high':close+1,'low':close-1,'close':close,'volume':100})
    _write_csv(ds/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],bars)
    store=DataStore(); paths=store.resolve('phase5')
    frame=store.load_bars(paths,'2026-01-01T00:05:00Z','2026-01-01T00:31:00Z','10m')
    assert list(frame.index.strftime('%H:%M')) == ['00:10','00:20','00:30']
    assert frame.iloc[0].open == 99.5
    assert frame.iloc[0].close == 101


def test_10m_range_can_use_preceding_five_minute_component(tmp_path, monkeypatch):
    data_root = tmp_path / 'data'; ds = data_root / 'boundary'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data_root))
    bars=[]
    for i, minute in enumerate((5,10,15,20)):
        close=100+i
        bars.append({'timestamp':f'2026-01-01T00:{minute:02d}:00Z','open':close-.5,'high':close+1,'low':close-1,'close':close,'volume':100})
    _write_csv(ds/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],bars)
    store=DataStore(); paths=store.resolve('boundary')
    # The 00:10 completed 10m candle needs the 00:05 source candle just before
    # the selected range start. V11 deliberately loads that one warm-in source row.
    frame=store.load_bars(paths,'2026-01-01T00:10:00Z','2026-01-01T00:21:00Z','10m')
    assert list(frame.index.strftime('%H:%M')) == ['00:10','00:20']
