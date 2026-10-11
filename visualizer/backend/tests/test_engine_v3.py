import csv
from pathlib import Path

from app.engine import run_backtest
from app.models import BacktestRequest, StrategyConfig, RuleGroup, Condition


def _write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)


def test_no_trade_blocks_then_call_uses_call_exit(tmp_path, monkeypatch):
    data_root = tmp_path / 'data'
    ds = data_root / 'sample'
    result_root = tmp_path / 'results'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data_root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(result_root))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))

    bars = []
    closes = [100, 101, 102, 103, 104, 105]
    for i, close in enumerate(closes):
        bars.append({
            'timestamp': f'2026-01-01T00:{i*5:02d}:00Z',
            'open': close - 0.5, 'high': close + 1, 'low': close - 1,
            'close': close, 'volume': 100,
        })
    _write_csv(ds / 'underlying_bars.csv', ['timestamp','open','high','low','close','volume'], bars)
    _write_csv(ds / 'option_instruments.csv', [
        'symbol','source_symbol','expiry','strike','option_type','activation','expiration',
        'price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'
    ], [{
        'symbol':'BTC100CE','source_symbol':'BTC100CE','expiry':'2026-01-02','strike':100,'option_type':'CE',
        'activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,
        'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001,
    }])
    quotes=[]
    for i in range(6):
        px=10+i
        quotes.append({'timestamp':f'2026-01-01T00:{i*5:02d}:00Z','symbol':'BTC100CE','bid':px,'ask':px+1,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000,'source_event':'test'})
    _write_csv(ds / 'option_quotes.csv', ['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest','source_event'], quotes)

    strategy = StrategyConfig(
        name='V3 engine behavior',
        call_entry=RuleGroup(conditions=[Condition(id='entry',left='close',operator='BETWEEN',value=100,value2=103)]),
        put_entry=RuleGroup(conditions=[Condition(id='never-put',left='close',operator='LT',value=0)]),
        call_exit=RuleGroup(mode='ANY', conditions=[Condition(id='call-exit',left='close',operator='GTE',value=104)]),
        put_exit=RuleGroup(mode='ANY', conditions=[Condition(id='wrong-put-exit',left='close',operator='GTE',value=103)]),
        no_trade=RuleGroup(mode='ALL', conditions=[Condition(id='block-early',left='close',operator='LT',value=103)]),
    )
    strategy.risk.stop_loss.mode='NONE'
    strategy.risk.profit_protection.mode='NONE'
    strategy.risk.max_hold_minutes=None
    strategy.option.min_dte_days=0
    strategy.option.max_dte_days=3
    strategy.option.max_spread_percent=20
    strategy.risk.quantity=1

    result = run_backtest(BacktestRequest(
        dataset_id='sample', start='2026-01-01T00:00:00Z', end='2026-01-01T00:30:00Z', strategy=strategy,
    ))
    assert result['metrics']['trades'] == 1
    trade = result['trades'][0]
    assert trade['signal_time'].startswith('2026-01-01T00:15:00')
    assert trade['exit_time'].startswith('2026-01-01T00:20:00')
    assert trade['exit_reason'] == 'CONDITION_EXIT'
    no_trade_markers = [m for m in result['markers'] if m['kind']=='reject' and m['details'].get('reason')=='NO_TRADE_CONDITION']
    assert len(no_trade_markers) == 3
