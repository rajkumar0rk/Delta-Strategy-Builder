from __future__ import annotations

import pandas as pd
import pytest

from app.data_store import DataStore
from app.trade_positions import closed_positions
from app.robustness_v163 import analyze_trade_robustness
from app.models import PatternTradeConfig
from app.research import run_ablation
from app.jobs import JobManager


def test_partial_legs_are_one_closed_economic_position():
    legs=[
        dict(position_group_id='a',pattern_trade={'type':'HAMMER'},partial_exit=True,
             entry_time='2026-01-01T00:00:00Z',exit_time='2026-01-01T00:10:00Z',
             net_pnl_usd=40,fees_usd=2,quantity=4),
        dict(position_group_id='a',pattern_trade={'type':'HAMMER'},partial_exit=False,
             entry_time='2026-01-01T00:00:00Z',exit_time='2026-01-01T00:20:00Z',
             net_pnl_usd=-70,fees_usd=3,quantity=4),
        dict(position_group_id='b',pattern_trade={'type':'HAMMER'},partial_exit=True,
             entry_time='2026-01-01T00:00:00Z',exit_time='2026-01-01T00:30:00Z',
             net_pnl_usd=50,fees_usd=2,quantity=2)]
    rows=closed_positions(legs)
    assert len(rows)==1
    assert rows[0]['net_pnl_usd']==-30
    assert rows[0]['fees_usd']==5
    assert rows[0]['quantity']==8
    assert rows[0]['exit_legs']==2
    report=analyze_trade_robustness(legs,simulations=100)
    assert report['closed_trades']==1
    assert report['historical_net_pnl_usd']==-30


def test_legacy_trades_still_remain_distinct():
    rows=[{'net_pnl_usd':10},{'net_pnl_usd':-5}]
    assert closed_positions(rows)==rows


def test_confirmation_window_is_configurable_but_bounded():
    assert PatternTradeConfig(confirmation_bars=3).confirmation_bars==3
    with pytest.raises(ValueError):
        PatternTradeConfig(confirmation_bars=49)


def test_frame_cache_eviction_keeps_under_memory_limit(monkeypatch):
    monkeypatch.setenv('STRATEGY_LAB_FRAME_CACHE_MB','1')
    cache=__import__('collections').OrderedDict()
    a=pd.DataFrame({'x':range(100000)})
    b=pd.DataFrame({'x':range(100000)})
    DataStore._cache_insert(cache,'a',a)
    DataStore._cache_insert(cache,'b',b)
    assert len(cache)==1
    assert list(cache)==['b']


def test_queue_limit_rejects_excess_and_preserves_existing_job(monkeypatch):
    monkeypatch.setenv('STRATEGY_LAB_MAX_WORKERS','1')
    monkeypatch.setenv('STRATEGY_LAB_MAX_PENDING_JOBS','1')
    manager=JobManager()
    from threading import Event
    block=Event()
    started=Event()
    def task(progress):
        started.set()
        block.wait(timeout=5)
    try:
        one=manager.create(task)
        assert started.wait(timeout=3)
        two=manager.create(task)
        with pytest.raises(RuntimeError,match='JOB_QUEUE_FULL'):
            manager.create(task)
        assert manager.get(one)['status']=='RUNNING'
        assert manager.get(two)['status']=='QUEUED'
    finally:
        block.set()
        manager._pool.shutdown(wait=True)


def test_api_queue_backpressure_returns_429(monkeypatch):
    from fastapi import HTTPException
    from app import main
    def saturated(_fn):
        raise RuntimeError("JOB_QUEUE_FULL: busy")
    monkeypatch.setattr(main.jobs,"create",saturated)
    with pytest.raises(HTTPException) as ex:
        main._enqueue(lambda progress: None)
    assert ex.value.status_code==429
    assert "JOB_QUEUE_FULL" in ex.value.detail


def test_legacy_csv_none_string_pattern_does_not_merge_positions():
    legs=[
        {'position_group_id':'same','pattern_trade':'None','partial_exit':'False','net_pnl_usd':'8'},
        {'position_group_id':'same','pattern_trade':'None','partial_exit':'False','net_pnl_usd':'-3'},
    ]
    assert len(closed_positions(legs))==2


def test_csv_string_pattern_partial_roundtrip():
    legs=[
        {'position_group_id':'p','pattern_trade':"{'pattern_type':'HAMMER'}",
         'partial_exit':'True','quantity':'2','net_pnl_usd':'15'},
        {'position_group_id':'p','pattern_trade':"{'pattern_type':'HAMMER'}",
         'partial_exit':'False','quantity':'2','net_pnl_usd':'-5'},
    ]
    out=closed_positions(legs)
    assert len(out)==1
    assert out[0]['net_pnl_usd']==10
    assert out[0]['quantity']==4
