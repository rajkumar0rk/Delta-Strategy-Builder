from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.data_store import DataStore
from app.models import StrategyConfig, TrendDiscoveryRequest
from app.trend_discovery import run_trend_discovery

UTC = timezone.utc


def _write_bars(path: Path, closes: list[float], start: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    with path.open('w', newline='', encoding='utf-8') as h:
        w = csv.DictWriter(h, fieldnames=['timestamp','open','high','low','close','volume'])
        w.writeheader()
        prev = closes[0]
        for i, close in enumerate(closes):
            ts = start + timedelta(minutes=5*i)
            op = prev
            w.writerow({
                'timestamp': ts.isoformat().replace('+00:00','Z'),
                'open': op, 'high': max(op, close)+0.1, 'low': min(op, close)-0.1,
                'close': close, 'volume': 100+i,
            })
            prev = close


def _catalog(root: Path, segments: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root/'catalog.json').write_text(json.dumps({
        'format_version': 1,
        'updated_at': '2026-10-08T15:42:38Z',
        'source': 'delta_india_public_history',
        'fidelity': 'LOW_FIDELITY_SYNTHETIC_BBO',
        'segments': segments,
    }), encoding='utf-8')


def test_catalog_is_authoritative_and_ignores_unlisted_folders(tmp_path, monkeypatch):
    root = tmp_path/'delta-history'
    _catalog(root, [{
        'name':'2026-a','directory':'segments/2026-a',
        'start':'2026-01-01T00:00:00Z','end_exclusive':'2026-01-02T00:00:00Z',
    }])
    _write_bars(root/'segments/2026-a/underlying_bars.csv', [100,101,102])
    _write_bars(root/'compat-old/underlying_bars.csv', [100,100,100])
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    parts = DataStore().discover()
    assert [p.id for p in parts] == ['segments/2026-a']
    info = DataStore().archive_payload()
    assert info['available'] is True
    assert info['source'] == 'delta_india_public_history'
    assert info['fidelity'] == 'LOW_FIDELITY_SYNTHETIC_BBO'
    assert info['segment_count'] == 1


def test_archive_mode_selects_only_overlapping_catalog_segments(tmp_path, monkeypatch):
    root = tmp_path/'delta-history'
    segments = [
        {'name':'jan','directory':'segments/jan','start':'2026-01-01T00:00:00Z','end_exclusive':'2026-02-01T00:00:00Z'},
        {'name':'feb','directory':'segments/feb','start':'2026-02-01T00:00:00Z','end_exclusive':'2026-03-01T00:00:00Z'},
    ]
    _catalog(root, segments)
    _write_bars(root/'segments/jan/underlying_bars.csv', [100,100])
    _write_bars(root/'segments/feb/underlying_bars.csv', [100,100], datetime(2026,2,1,tzinfo=UTC))
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    req = SimpleNamespace(dataset_mode='ARCHIVE', start='2026-02-10T00:00:00Z', end='2026-02-11T00:00:00Z')
    parts = DataStore().resolve_request(req, require_options=False)
    assert [p.id for p in parts] == ['segments/feb']


def test_archive_gap_is_reported(tmp_path, monkeypatch):
    root = tmp_path/'delta-history'
    _catalog(root, [
        {'name':'a','directory':'segments/a','start':'2026-01-01T00:00:00Z','end_exclusive':'2026-01-02T00:00:00Z'},
        {'name':'b','directory':'segments/b','start':'2026-01-03T00:00:00Z','end_exclusive':'2026-01-04T00:00:00Z'},
    ])
    _write_bars(root/'segments/a/underlying_bars.csv', [100,100])
    _write_bars(root/'segments/b/underlying_bars.csv', [100,100], datetime(2026,1,3,tzinfo=UTC))
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    coverage = DataStore().archive_range_coverage('2026-01-01T12:00:00Z','2026-01-03T12:00:00Z')
    assert coverage['covered'] is False
    assert coverage['gaps'][0]['start'].startswith('2026-01-02')
    assert coverage['gaps'][0]['end_exclusive'].startswith('2026-01-03')


def test_trend_discovery_finds_big_and_fake_call_samples(tmp_path, monkeypatch):
    root = tmp_path/'delta-history'
    start = datetime(2026,1,1,tzinfo=UTC)
    closes = [100.0]*28 + [100.4,101.0,102.0,103.0,104.0] + [104.0]*47
    end_exclusive = start + timedelta(minutes=5*len(closes))
    _catalog(root, [{
        'name':'sample','directory':'segments/sample',
        'start':start.isoformat().replace('+00:00','Z'),
        'end_exclusive':end_exclusive.isoformat().replace('+00:00','Z'),
    }])
    _write_bars(root/'segments/sample/underlying_bars.csv', closes, start)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))

    strategy = StrategyConfig.model_validate({
        'name':'V13 discovery test', 'timeframe':'5m', 'direction_mode':'CALL',
        'call_entry': {'mode':'ALL','min_pass':1,'conditions':[{'id':'always','left':'close','operator':'GT','value':0}],'groups':[]},
        'call_big_trend_score': {'enabled':True,'threshold':70,'mode':'GATE','components':[{'condition_id':'always','weight':100}]},
    })
    req = TrendDiscoveryRequest(
        dataset_mode='ARCHIVE', start=start.isoformat().replace('+00:00','Z'),
        end=end_exclusive.isoformat().replace('+00:00','Z'), strategy=strategy,
        lookahead_bars=6, big_move_percent=2.0, candidate_score_threshold=70,
        prelude_bars=3, min_separation_bars=6, max_events=100,
    )
    result = run_trend_discovery(req)
    assert result['counts']['BIG_CALL'] >= 1
    assert result['counts']['FAKE_CALL'] >= 1
    assert result['bars_analyzed'] == len(closes)
    assert any(x['direction']=='CALL' for x in result['score_calibration'])
    assert 'future candles only for historical outcome labeling' in result['research_note']
