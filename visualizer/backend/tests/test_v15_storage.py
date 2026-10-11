from __future__ import annotations

import json
from pathlib import Path

from app import storage


def _legacy_run(root: Path, name: str = '20261009-000000-test') -> Path:
    p = root / name
    p.mkdir(parents=True)
    summary = {
        'run_id': name,
        'result_dir': str(p),
        'strategy': {'name': 'Legacy'},
        'metrics': {'trades': 1, 'net_pnl_usd': 1.0},
        'trades': [{'id': 1, 'net_pnl_usd': 1.0}],
        'markers': [{'time': '2026-01-01T00:00:00Z', 'kind': 'entry'}] * 100,
        'equity_curve': [{'timestamp': '2026-01-01T00:00:00Z', 'equity_usd': 101.0}] * 100,
        'series_meta': [{'key': 'ema'}] * 50,
        'decision_count': 100,
    }
    (p / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (p / 'markers.json').write_text(json.dumps(summary['markers'], indent=2), encoding='utf-8')
    (p / 'decision_events.csv').write_text('id,kind,passed\n' + ''.join(f'{i},ENTRY,false\n' for i in range(5000)), encoding='utf-8')
    (p / 'equity_curve.csv').write_text('timestamp,equity_usd\n' + ''.join('2026-01-01T00:00:00Z,101\n' for _ in range(5000)), encoding='utf-8')
    (p / 'trades.csv').write_text('id,net_pnl_usd\n1,1.0\n', encoding='utf-8')
    (p / f'{name}-analysis.zip').write_bytes(b'x' * 1000)
    return p


def test_optimize_existing_compresses_and_slims(tmp_path, monkeypatch):
    results = tmp_path / 'results'
    cache = tmp_path / '.cache'
    path = _legacy_run(results)
    monkeypatch.setattr(storage, 'result_root', lambda: results)
    monkeypatch.setattr(storage, 'cache_root', lambda: cache)

    before = storage.directory_size(path)
    report = storage.optimize_existing()
    after = storage.directory_size(path)

    assert report['saved_bytes'] > 0
    assert after < before
    assert not (path / 'decision_events.csv').exists()
    assert (path / 'decision_events.csv.gz').exists()
    assert not (path / 'equity_curve.csv').exists()
    assert (path / 'equity_curve.csv.gz').exists()
    assert not (path / 'markers.json').exists()
    assert (path / 'markers.json.gz').exists()
    assert not list(path.glob('*-analysis.zip'))
    summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    assert 'trades' not in summary
    assert 'markers' not in summary
    assert 'equity_curve' not in summary
    assert summary['artifact_manifest']['decisions'] == 'decision_events.csv.gz'


def test_load_result_reconstructs_compressed_artifacts(tmp_path, monkeypatch):
    results = tmp_path / 'results'
    cache = tmp_path / '.cache'
    path = _legacy_run(results)
    monkeypatch.setattr(storage, 'result_root', lambda: results)
    monkeypatch.setattr(storage, 'cache_root', lambda: cache)
    storage.optimize_run(path)

    result = storage.load_result(path.name)
    assert result is not None
    assert len(result['trades']) == 1
    assert len(result['markers']) == 100
    assert len(result['equity_curve']) == 5000


def test_cleanup_never_deletes_pinned_run(tmp_path, monkeypatch):
    results = tmp_path / 'results'; results.mkdir()
    cache = tmp_path / '.cache'; cache.mkdir()
    a = _legacy_run(results, '20250101-000000-old')
    b = _legacy_run(results, '20250102-000000-pinned')
    (b / '.pinned').write_text('pinned\n', encoding='utf-8')
    monkeypatch.setattr(storage, 'result_root', lambda: results)
    monkeypatch.setattr(storage, 'cache_root', lambda: cache)
    monkeypatch.setattr(storage, '_settings_path', lambda: tmp_path / '.storage.json')
    storage.save_settings({'retention_days': 0, 'keep_recent_runs': 0, 'result_limit_gb': 0.1, 'auto_cleanup_enabled': False})

    out = storage.cleanup_unpinned(dry_run=False)
    assert out['deleted_count'] == 1
    assert not a.exists()
    assert b.exists()


def test_analysis_storage_mode_writes_compressed_artifacts_and_cache_replays(tmp_path, monkeypatch):
    import csv
    from app.engine import run_backtest
    from app.models import BacktestRequest, StrategyConfig, RuleGroup, Condition

    data = tmp_path / 'data'; ds = data / 'sample'; ds.mkdir(parents=True)
    def write(name, fields, rows):
        with (ds / name).open('w', encoding='utf-8', newline='') as h:
            w = csv.DictWriter(h, fieldnames=fields); w.writeheader(); w.writerows(rows)
    write('underlying_bars.csv',['timestamp','open','high','low','close','volume'],[
        {'timestamp':'2026-01-01T00:00:00Z','open':100000,'high':100100,'low':99900,'close':100000,'volume':100},
        {'timestamp':'2026-01-01T00:05:00Z','open':100000,'high':100200,'low':99950,'close':100100,'volume':100},
        {'timestamp':'2026-01-01T00:10:00Z','open':100100,'high':100300,'low':100000,'close':100200,'volume':100},
    ])
    write('option_instruments.csv',['symbol','source_symbol','expiry','strike','option_type','activation','expiration','price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],[
        {'symbol':'BTC100000CE','source_symbol':'BTC100000CE','expiry':'2026-01-02','strike':100000,'option_type':'CE','activation':'2025-12-31T00:00:00Z','expiration':'2026-01-02T00:00:00Z','price_precision':2,'size_precision':0,'price_increment':1,'size_increment':1,'lot_size':1,'min_quantity':1,'contract_value':0.001},
    ])
    write('option_quotes.csv',['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest'],[
        {'timestamp':'2026-01-01T00:00:00Z','symbol':'BTC100000CE','bid':499,'ask':500,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000},
        {'timestamp':'2026-01-01T00:05:00Z','symbol':'BTC100000CE','bid':599,'ask':600,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000},
        {'timestamp':'2026-01-01T00:10:00Z','symbol':'BTC100000CE','bid':699,'ask':700,'bid_size':100,'ask_size':100,'volume':100,'open_interest':1000},
    ])
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path/'cache'))
    s = StrategyConfig(name='analysis storage', direction_mode='CALL', call_entry=RuleGroup(conditions=[Condition(id='e',left='close',operator='GTE',value=100000)]), call_exit=RuleGroup(mode='ANY',conditions=[Condition(id='x',left='close',operator='GTE',value=100100)]))
    s.risk.stop_loss.mode='NONE'; s.risk.take_profit.mode='NONE'; s.risk.profit_protection.mode='NONE'; s.risk.max_hold_minutes=None; s.risk.quantity=1
    s.option.min_dte_days=0; s.option.max_dte_days=3; s.option.max_spread_percent=20
    req = BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',end='2026-01-01T00:15:00Z',strategy=s,storage_mode='ANALYSIS')
    r = run_backtest(req)
    out = Path(r['result_dir'])
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    assert 'trades' not in summary and 'markers' not in summary and 'equity_curve' not in summary
    assert (out/'markers.json.gz').exists()
    assert (out/'equity_curve.csv.gz').exists()
    assert (out/'decision_events.csv.gz').exists()
    assert not (out/'decision_events.csv').exists()
    r2 = run_backtest(req)
    assert r2['cache_hit'] is True
    assert len(r2['trades']) == 1
    assert len(r2['equity_curve']) >= 1
