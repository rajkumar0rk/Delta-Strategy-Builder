from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import (
    BacktestRequest, ExecutionReplayRequest, HoldoutResearchRequest, StrategyConfig,
)
from app.robustness_v163 import analyze_trade_robustness
from app.engine import _effective_quote
from app.research import run_execution_replay, run_holdout


def _range():
    return dict(dataset_id='dummy',start='2026-01-01T00:00:00Z',
                end='2026-01-10T00:00:00Z',strategy=StrategyConfig())


def test_adverse_half_spread_is_zero_backward_compatible():
    strategy=StrategyConfig()
    q={'bid':98.,'ask':102.,'timestamp':'2026-01-01T00:00:00Z'}
    assert _effective_quote(q,strategy.execution) is q
    strategy.execution.extra_half_spread_percent=1.0
    widened=_effective_quote(q,strategy.execution)
    assert widened['bid']==pytest.approx(97.0)
    assert widened['ask']==pytest.approx(103.0)
    assert q['bid']==98.0


def test_scenario_validation_rejects_large_product_and_combined_tick_cap():
    with pytest.raises(ValidationError):
        ExecutionReplayRequest(**_range(),extra_half_spread_percent=[0,1,2,3,4],
                               extra_slippage_ticks=[0,1,2])
    st=StrategyConfig()
    st.execution.slippage_ticks=99
    with pytest.raises(ValidationError):
        ExecutionReplayRequest(**{**_range(),'strategy':st},
                               extra_slippage_ticks=[2])


def test_bootstrap_is_deterministic_and_outlier_driven():
    trades=[{'exit_time':f'2026-01-01T00:{i:02d}:00Z','net_pnl_usd':p}
            for i,p in enumerate([20,-3,-3,-3])]
    a=analyze_trade_robustness(trades,simulations=200,seed=77)
    b=analyze_trade_robustness(trades,simulations=200,seed=77)
    assert a==b
    assert a['net_excluding_best_usd']==pytest.approx(-9)
    assert a['net_excluding_top_3_usd']==pytest.approx(-3)
    assert a['status']=='LOW_SAMPLE_WARNING'
    assert a['bootstrap_net_pnl_usd_p05'] <= a['bootstrap_net_pnl_usd_median'] <= a['bootstrap_net_pnl_usd_p95']


def test_no_closed_trades_never_claims_positive_odds():
    report=analyze_trade_robustness([])
    assert report['status']=='INSUFFICIENT_TRADES'
    assert report['simulations']==0


def test_full_replay_calls_backtest_for_each_scenario(monkeypatch):
    seen=[]
    def fake(req, progress=None):
        seen.append((req.strategy.execution.extra_half_spread_percent,
                     req.strategy.execution.slippage_ticks))
        return {'run_id':str(len(seen)),'trades':[{'net_pnl_usd':1}],
                'metrics':{'trades':1,'net_pnl_usd':100-10*seen[-1][0]-seen[-1][1]}}
    monkeypatch.setattr('app.research.run_backtest',fake)
    req=ExecutionReplayRequest(**_range(),extra_half_spread_percent=[0,1],
                                extra_slippage_ticks=[0,1])
    result=run_execution_replay(req)
    assert len(seen)==4
    assert seen==[(0,0),(0,1),(1,0),(1,1)]
    assert result['scenarios'][0]['delta_net_pnl_usd']==0
    assert result['scenarios'][-1]['delta_net_pnl_usd']==-11


def test_holdout_has_nonoverlapping_contiguous_utc_blocks(monkeypatch):
    called=[]
    def fake(req, progress=None):
        called.append(req)
        return {'run_id':str(len(called)),'trades':[],'metrics':{'trades':0,'net_pnl_usd':0}}
    monkeypatch.setattr('app.research.run_backtest',fake)
    req=HoldoutResearchRequest(**_range(),train_fraction=.7,embargo_bars=12)
    result=run_holdout(req)
    assert len(called)==2
    assert called[0].end < called[1].start
    assert result['holdout']['robustness']['status']=='INSUFFICIENT_TRADES'
    assert result['embargo_bars']==12



def test_replay_progress_scales_inner_backtests_monotonically(monkeypatch):
    snapshots = []
    runs = []

    def fake(req, progress=None):
        runs.append(req)
        if progress:
            progress('Loading quotes', 25, 'LOAD_BARS', 'Index quotes')
            progress('Evaluating candles', 80, 'BACKTEST_LOOP', 'Finalize')
        return {'run_id':str(len(runs)), 'trades':[], 'metrics':{'net_pnl_usd':0}}

    monkeypatch.setattr('app.research.run_backtest', fake)
    req = ExecutionReplayRequest(
        **_range(), extra_half_spread_percent=[0, 1],
        extra_slippage_ticks=[0],
    )

    def collect(message, percent=None, stage=None, next_step=None):
        snapshots.append((message, percent, stage, next_step))

    result = run_execution_replay(req, collect)
    assert result['scenario_count'] == 2
    assert len(runs) == 2
    assert [e[1] for e in snapshots] == sorted(e[1] for e in snapshots)
    assert snapshots[0][1] == 0
    assert snapshots[-1][1] == 100
    assert any('1/2' in row[0] and row[1] == 12.5 for row in snapshots)
    assert any('2/2' in row[0] and row[1] == 62.5 for row in snapshots)
    assert all(row[2] == 'EXECUTION_REPLAY' for row in snapshots)


def test_holdout_progress_runs_train_then_holdout(monkeypatch):
    snapshots = []
    runs = []

    def fake(req, progress=None):
        runs.append(req)
        if progress:
            progress('Calculating indicators', 50, 'INDICATORS', 'Evaluate')
        return {'run_id':str(len(runs)), 'trades':[], 'metrics':{'net_pnl_usd':0}}

    monkeypatch.setattr('app.research.run_backtest', fake)
    req = HoldoutResearchRequest(**_range(), train_fraction=0.7, embargo_bars=12)
    result = run_holdout(
        req,
        lambda msg, pct, stage, next_step: snapshots.append((msg,pct,stage)),
    )
    assert result['kind'] == 'CHRONOLOGICAL_HOLDOUT'
    assert len(runs) == 2
    assert [x[1] for x in snapshots] == sorted(x[1] for x in snapshots)
    assert [x[1] for x in snapshots if 'Calculating indicators' in x[0]] == [25,75]
    assert snapshots[0][1] == 0
    assert snapshots[-1][1] == 100
    assert snapshots[-1][2] == 'HOLDOUT_TEST'


def test_replay_cancellation_interrupts_between_inner_checkpoints(monkeypatch):
    runs = []

    def fake(req, progress=None):
        runs.append(req)
        if progress:
            progress('Loading quotes', 25, 'LOAD_BARS', 'Index quotes')
        return {'run_id':str(len(runs)), 'trades':[], 'metrics':{'net_pnl_usd':0}}

    class Cancelled(RuntimeError):
        pass

    monkeypatch.setattr('app.research.run_backtest', fake)
    req = ExecutionReplayRequest(
        **_range(), extra_half_spread_percent=[0,1],
        extra_slippage_ticks=[0],
    )
    def interrupt(message, percent=None, stage=None, next_step=None):
        if 'Loading quotes' in message:
            raise Cancelled('Stopped')

    with pytest.raises(Cancelled, match='Stopped'):
        run_execution_replay(req, interrupt)
    assert len(runs) == 1
