import pandas as pd
import pytest

from app.engine import (
    _big_trend_score,
    _prepare_big_trend_columns,
    _prepare_breakout_columns,
    _prepare_trend_phase_columns,
    _fee_edge_check,
)
from app.models import (
    StrategyConfig, RuleGroup, Condition, BigTrendScoreConfig,
    BigTrendScoreComponent, BreakoutRetestConfig, TrendPhaseConfig,
)
from app.rules import evaluate_condition


def frame(values, *, name='x'):
    idx=pd.date_range('2026-01-01',periods=len(values),freq='5min',tz='UTC')
    close=pd.Series(values,index=idx,dtype=float)
    return pd.DataFrame({name:close,'open':close,'high':close+0.4,'low':close-0.4,'close':close,'volume':100.0},index=idx)


def test_continuous_weighted_scoring_is_partial_not_binary():
    f=frame([30.0])
    g=RuleGroup(conditions=[Condition(id='adx',left='x',operator='GTE',value=20)])
    cfg=BigTrendScoreConfig(enabled=True,threshold=40,components=[
        BigTrendScoreComponent(condition_id='adx',weight=10,scoring_mode='CONTINUOUS',zero_at=20,full_at=40)
    ])
    out=_big_trend_score(f,0,g,cfg)
    assert out['score']==pytest.approx(50.0)
    assert out['components'][0]['fraction']==pytest.approx(0.5)


def test_score_persistence_and_score_as_rule_operand():
    f=frame([90,70,85])
    g=RuleGroup(conditions=[Condition(id='strength',left='x',operator='GTE',value=0)])
    cfg=BigTrendScoreConfig(enabled=True,threshold=80,persistence_hits=2,persistence_window=3,require_current_threshold=False,components=[
        BigTrendScoreComponent(condition_id='strength',weight=1,scoring_mode='CONTINUOUS',zero_at=0,full_at=100)
    ])
    s=StrategyConfig(direction_mode='CALL',call_entry=g,call_big_trend_score=cfg)
    _prepare_big_trend_columns(f,s)
    assert list(f['call_big_trend_score'].round(1))==[90.0,70.0,85.0]
    assert f['call_big_trend_score_persistence_count'].iloc[-1]==pytest.approx(2.0)
    assert f['call_big_trend_score_persisted'].iloc[-1]==pytest.approx(1.0)
    c=Condition(id='score-rule',left='call_big_trend_score',operator='GTE',value=80)
    assert evaluate_condition(f,2,c)['passed']


def test_breakout_snapshot_then_retest_hold_becomes_ready():
    idx=pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC')
    f=pd.DataFrame({
        'open':[99,100,101,100.4,101],
        'high':[99.5,101.6,102.4,101.0,102],
        'low':[98.5,99.8,100.8,99.9,100.8],
        'close':[99,101,102,100.3,101.5],
        'volume':[100]*5,
        'level':[100]*5,
    },index=idx,dtype=float)
    g=RuleGroup(conditions=[Condition(id='bo',left='close',operator='CROSSES_ABOVE',right='level')])
    s=StrategyConfig(direction_mode='CALL',call_entry=g,call_breakout_retest=BreakoutRetestConfig(
        enabled=True,breakout_condition_id='bo',breakout_level_operand='level',tolerance_mode='POINTS',tolerance_value=0.5,
        max_retest_wait_bars=4,hold_bars=1,require_retest_for_entry=True,max_trend_age_bars=10,
    ))
    _prepare_big_trend_columns(f,s)
    _prepare_breakout_columns(f,s,'call')
    assert f['call_breakout_level'].iloc[1]==pytest.approx(100)
    assert f['call_bars_since_breakout'].iloc[3]==pytest.approx(2)
    assert f['call_retest_seen'].iloc[3]==pytest.approx(1)
    assert f['call_retest_ready'].iloc[3]==pytest.approx(1)


def test_false_breakout_blocks_until_trigger_rearms():
    idx=pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC')
    f=pd.DataFrame({
        'open':[99,100,100,99,100], 'high':[99.5,101.5,100.5,99.5,101.5], 'low':[98.5,99.5,98.5,98.5,99.5],
        'close':[99,101,99,99,101], 'volume':[100]*5, 'level':[100]*5,
    },index=idx,dtype=float)
    g=RuleGroup(conditions=[Condition(id='bo',left='close',operator='CROSSES_ABOVE',right='level')])
    s=StrategyConfig(direction_mode='CALL',call_entry=g,call_breakout_retest=BreakoutRetestConfig(
        enabled=True,breakout_condition_id='bo',breakout_level_operand='level',tolerance_mode='POINTS',tolerance_value=0.2,
        false_breakout_window_bars=3,block_false_breakout_until_rearm=True,max_trend_age_bars=10,
    ))
    _prepare_big_trend_columns(f,s); _prepare_breakout_columns(f,s,'call')
    assert f['call_false_breakout'].iloc[2]==pytest.approx(1)
    assert f['call_breakout_blocked'].iloc[2]==pytest.approx(1)
    # One full false-trigger candle resets the block; the later fresh cross can arm again.
    assert f['call_breakout_blocked'].iloc[3]==pytest.approx(0)
    assert f['call_breakout_active'].iloc[4]==pytest.approx(1)


def test_trend_phase_state_machine_progresses_and_exhausts():
    f=frame([20,60,75,85,85,50,30])
    g=RuleGroup(conditions=[Condition(id='strength',left='x',operator='GTE',value=0)])
    s=StrategyConfig(
        direction_mode='CALL',call_entry=g,
        call_big_trend_score=BigTrendScoreConfig(enabled=True,threshold=80,persistence_hits=2,persistence_window=2,require_current_threshold=True,components=[
            BigTrendScoreComponent(condition_id='strength',weight=1,scoring_mode='CONTINUOUS',zero_at=0,full_at=100)
        ]),
        call_trend_phase=TrendPhaseConfig(enabled=True,compression_max_score=45,ignition_min_score=55,confirmation_min_score=70,big_trend_min_score=80,exhaustion_below_score=55),
    )
    _prepare_big_trend_columns(f,s); _prepare_breakout_columns(f,s,'call'); _prepare_trend_phase_columns(f,s,'call')
    phases=f['call_trend_phase_code'].tolist()
    assert phases[:5]==[0.0,1.0,2.0,2.0,3.0]
    assert phases[5]==4.0
    assert phases[6]==0.0


def test_fee_edge_filter_blocks_move_smaller_than_spread_and_fees():
    s=StrategyConfig(direction_mode='CALL')
    s.execution.fee_edge_filter.enabled=True
    s.execution.fee_edge_filter.expected_option_move_percent=1.0
    s.execution.fee_edge_filter.min_edge_multiple=1.0
    spec={'contract_value':0.001,'price_increment':1}
    q={'bid':90,'ask':110,'volume':100,'open_interest':1000}
    ok,reason,details=_fee_edge_check(s,spec,q,100000,110,10)
    assert not ok
    assert reason=='INSUFFICIENT_FEE_ADJUSTED_EDGE'
    assert details['estimated_friction_usd'] > details['expected_move_usd']

def test_setup_only_breakout_condition_can_be_ignored_at_retest_entry():
    idx=pd.date_range('2026-01-01',periods=3,freq='5min',tz='UTC')
    f=pd.DataFrame({'close':[99,101,101.2],'confirm':[0,0,1],'level':[100,100,100]},index=idx,dtype=float)
    g=RuleGroup(mode='ALL',conditions=[
        Condition(id='bo',left='close',operator='CROSSES_ABOVE',right='level'),
        Condition(id='confirm',left='confirm',operator='GTE',value=1),
    ])
    # At the retest/continuation candle the breakout cross itself is no longer true,
    # but the setup-only version should evaluate the remaining confirmation rule.
    from app.rules import evaluate_group
    normal=evaluate_group(f,2,g)
    setup_only=evaluate_group(f,2,g,{'bo'})
    assert normal['passed'] is False
    assert setup_only['passed'] is True
    assert setup_only['total']==1
