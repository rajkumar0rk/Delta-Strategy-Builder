from app.models import StrategyConfig, IndicatorInstance, RuleGroup, Condition
from app.research import _set_path, _remove_indicator_conditions


def test_sweep_path_can_change_indicator_condition_and_nested_field():
    s=StrategyConfig(
        indicators=[IndicatorInstance(id='ema9',kind='EMA',params={'period':9,'source':'close'})],
        call_entry=RuleGroup(conditions=[Condition(id='gap',left='close',operator='GT_BY_POINTS',right='ema9',value=10)]),
    ).model_dump(mode='json')
    _set_path(s,'indicator:ema9:period',12)
    _set_path(s,'condition:call_entry:gap:value',25)
    _set_path(s,'call_entry_behavior.delay_bars',2)
    assert s['indicators'][0]['params']['period']==12
    assert s['call_entry']['conditions'][0]['value']==25
    assert s['call_entry_behavior']['delay_bars']==2


def test_ablation_removes_conditions_that_reference_indicator():
    s=StrategyConfig(
        indicators=[IndicatorInstance(id='ema9',kind='EMA',params={'period':9,'source':'close'})],
        call_entry=RuleGroup(conditions=[
            Condition(id='uses',left='close',operator='GT',right='ema9'),
            Condition(id='keeps',left='close',operator='GT',value=100),
        ]),
    ).model_dump(mode='json')
    removed=set();_remove_indicator_conditions(s['call_entry'],'ema9',removed)
    assert removed=={'uses'}
    assert [x['id'] for x in s['call_entry']['conditions']]==['keeps']


def test_v7_monthly_robustness_counts_flat_and_negative_months():
    from app.research import _robustness
    r=_robustness({'trades':[
        {'entry_time':'2026-01-10T00:00:00Z','net_pnl_usd':2.0},
        {'entry_time':'2026-02-10T00:00:00Z','net_pnl_usd':-1.0},
    ]},'2026-01-01T00:00:00Z','2026-04-01T00:00:00Z')
    assert r['months_tested']==3
    assert r['positive_months']==1
    assert r['negative_months']==1
    assert r['flat_months']==1
    assert r['worst_month_net_pnl_usd']==-1.0


def test_v7_walk_forward_selects_training_winner_then_tests_next_block(monkeypatch):
    from app.models import ResearchSweepRequest, SweepDimension
    from app.research import _walk_forward
    import app.research as research
    base=StrategyConfig()
    def fake(req):
        value=float(req.strategy.risk.stop_loss.value)
        return {'run_id':f'run-{value}', 'cache_hit':False, 'metrics':{
            'net_pnl_usd':value,'profit_factor':1+value/100,'max_closed_trade_drawdown_usd':1,
            'trades':1,'wins':1,'losses':0,'win_rate_percent':100,
        }, 'trades':[{'net_pnl_usd':value,'entry_time':req.start}]}
    monkeypatch.setattr(research,'run_backtest',fake)
    req=ResearchSweepRequest(dataset_id='x',start='2026-01-01T00:00:00Z',end='2026-04-01T00:00:00Z',strategy=base,dimensions=[SweepDimension(path='risk.stop_loss.value',values=[10,20])],walk_forward_folds=2,max_combinations=10)
    out=_walk_forward(req,[(10.0,),(20.0,)])
    assert out is not None
    assert len(out['folds'])==2
    assert all(f['selected_parameters']['risk.stop_loss.value']==20.0 for f in out['folds'])
    assert out['summary']['positive_test_folds']==2
