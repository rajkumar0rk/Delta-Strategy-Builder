"""Futures OHLC backtests must not require optional 1m observation DNS access."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.engine import run_backtest
from app.models import BacktestRequest, StrategyConfig


def _sample(tmp_path, monkeypatch):
    root=tmp_path/'delta-history'
    folder=root/'segments'/'sample'
    folder.mkdir(parents=True)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    (root/'catalog.json').write_text(json.dumps({
        'format_version':1,'source':'fixture','fidelity':'LOW_FIDELITY_SYNTHETIC_BBO',
        'segments':[{'name':'sample','directory':'segments/sample',
                     'start':'2026-01-01T00:00:00Z',
                     'end_exclusive':'2026-01-02T00:00:00Z'}]
    }),encoding='utf-8')
    with (folder/'underlying_bars.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['timestamp','open','high','low','close','volume'])
        writer.writeheader()
        for i in range(24):
            writer.writerow({'timestamp':f'2026-01-01T{i//12:02d}:{(i%12)*5:02d}:00Z',
                             'open':100+i,'high':102+i,'low':99+i,
                             'close':101+i,'volume':100})
    strategy=StrategyConfig(
        market_type='FUTURES',direction_mode='CALL')
    strategy.futures.funding_mode='EXCLUDE_WITH_WARNING'
    strategy.risk.max_hold_minutes=None
    return BacktestRequest(
        dataset_mode='ARCHIVE',start='2026-01-01T00:00:00Z',
        end='2026-01-01T02:00:00Z',strategy=strategy,
        storage_mode='COMPACT')


def test_default_futures_request_does_not_download_supplemental_observations(tmp_path,monkeypatch):
    req=_sample(tmp_path,monkeypatch)
    from app import futures_history_sync
    monkeypatch.setattr(futures_history_sync,'ensure_futures_observations',
                        lambda *_args,**_kw: (_ for _ in ()).throw(
                            RuntimeError('DNS unavailable: should never call optional sync')))
    result=run_backtest(req)
    assert result['strategy']['market_type']=='FUTURES'
    assert result['reliability']['grade']=='RESEARCH_ONLY'
    assert req.auto_sync_futures_observations is False


def test_btc_archive_repair_does_not_imply_observation_sync(tmp_path,monkeypatch):
    req=_sample(tmp_path,monkeypatch)
    req.auto_download_missing_data=True
    from app import archive_sync,futures_history_sync
    calls=[]
    monkeypatch.setattr(archive_sync,'ensure_archive_data',
                        lambda *_args,**_kw: calls.append('btc_archive'))
    monkeypatch.setattr(futures_history_sync,'ensure_futures_observations',
                        lambda *_args,**_kw: calls.append('futures_observations'))
    result=run_backtest(req)
    assert result['metrics']['trades']>=0
    assert calls==['btc_archive']


def test_explicit_optional_observation_sync_is_honored(tmp_path,monkeypatch):
    req=_sample(tmp_path,monkeypatch)
    req.auto_sync_futures_observations=True
    from app import futures_history_sync
    calls=[]
    monkeypatch.setattr(futures_history_sync,'ensure_futures_observations',
                        lambda start,end,progress=None: calls.append((start,end)))
    result=run_backtest(req)
    assert result['strategy']['market_type']=='FUTURES'
    assert calls==[(req.start,req.end)]


def test_requested_observation_sync_failure_is_not_silently_ignored(tmp_path,monkeypatch):
    req=_sample(tmp_path,monkeypatch)
    req.auto_sync_futures_observations=True
    from app import futures_history_sync
    def outage(*_args,**_kwargs):
        raise RuntimeError('FUTURES_OBSERVATION_DNS_FAILURE: DNS unavailable')
    monkeypatch.setattr(futures_history_sync,'ensure_futures_observations',outage)
    with pytest.raises(RuntimeError,match='FUTURES_OBSERVATION_DNS_FAILURE'):
        run_backtest(req)


def test_separate_request_flags_do_not_change_strategy_json():
    strategy=StrategyConfig(market_type='FUTURES')
    request=BacktestRequest(dataset_mode='ARCHIVE',start='2026-01-01T00:00:00Z',
                            end='2026-01-02T00:00:00Z',strategy=strategy,
                            auto_download_missing_data=True,
                            auto_sync_futures_observations=False)
    assert request.model_dump()['auto_sync_futures_observations'] is False
    assert 'auto_sync_futures_observations' not in strategy.model_dump()
