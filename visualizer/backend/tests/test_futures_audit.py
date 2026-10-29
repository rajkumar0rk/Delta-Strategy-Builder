from __future__ import annotations
from app.futures_audit import audit_futures_parity


def sample():
    trade={'id':1,'direction':'LONG','entry_time':'2026-01-01T00:05:00Z',
           'exit_time':'2026-01-01T00:15:00Z','entry_price':100.5,
           'exit_price':109.5,'quantity':0.001,'entry_fee_usd':0.001,
           'exit_fee_usd':0.001,'fees_usd':0.002,'funding_usd':0,
           'gross_pnl_usd':0.009,'net_pnl_usd':0.007}
    return ({'strategy':{'market_type':'FUTURES'},'trades':[trade],
             'metrics':{'net_pnl_usd':0.007},'markers':[
                 {'time':1767225900,'kind':'entry','direction':'CALL'},
                 {'time':1767226500,'kind':'exit','direction':'CALL'}]},
            {'bars':[{'time':1767226200,'open':100}],
             'condition_states':[{'time':1767225900,'call_passed':True,
                'no_trade_active':False,'call_no_trade_active':False,'call_delay_ready':True}]})


def test_audit_reconciles_signal_entry_fill_and_net():
    result,chart=sample()
    out=audit_futures_parity(result,chart,timeframe_minutes=5)
    assert out['status']=='PASSED_RESEARCH_ONLY',out['failures']
    assert out['checked_preview_signals']==1
    assert out['checked_ohlc_entry_fills']==1
    assert not out['exchange_fills_verified']


def test_audit_fails_on_wrong_signal_and_accounting():
    result,chart=sample()
    chart['condition_states'][0]['call_passed']=False
    result['trades'][0]['net_pnl_usd']=1
    out=audit_futures_parity(result,chart,timeframe_minutes=5)
    assert out['status']=='FAILED'
    assert any('rule pass' in issue for issue in out['failures'])
    assert any('Net P&L' in issue for issue in out['failures'])


def test_audit_rejects_options():
    result,chart=sample()
    result['strategy']['market_type']='OPTIONS'
    try:
        audit_futures_parity(result,chart,timeframe_minutes=5)
    except ValueError:
        return
    assert False, 'Must reject option runs'


def test_audit_fails_closed_for_missing_signal_or_execution_bar():
    result,chart=sample()
    chart['condition_states']=[]
    chart['bars']=[]
    report=audit_futures_parity(result,chart,timeframe_minutes=5)
    assert report['status']=='FAILED'
    assert report['checked_preview_signals']==0
    assert report['checked_ohlc_entry_fills']==0
    assert any('Missing' in x for x in report['failures'])


def test_audit_flags_exact_fill_mismatch():
    result,chart=sample()
    result['trades'][0]['entry_price']=101
    assert any('configured adverse slippage' in x for x in
        audit_futures_parity(result,chart,timeframe_minutes=5)['failures'])


def test_audit_rejects_ineligible_entry_provenance():
    result,chart=sample()
    result['trades'][0].update(
        entry_lifecycle_id='life-1',
        entry_lifecycle_signal_time='2026-01-01T00:05:00Z',
        entry_lifecycle_age_bars=1,
        entry_lifecycle_delay_bars=2,
        entry_lifecycle_entries_before=1,
        entry_lifecycle_max_entries=1,
        entry_lifecycle_expired=True,
        entry_lifecycle_eligible=False,
    )
    report=audit_futures_parity(result,chart,timeframe_minutes=5)
    assert report['status']=='FAILED'
    assert any('lifecycle' in item.lower() for item in report['failures'])


def test_independent_lifecycle_replay_accepts_completed_candle_next_open():
    from app.futures_lifecycle_replay import independently_replay_lifecycles
    from app.models import StrategyConfig, EntryBehavior
    st=StrategyConfig(market_type="FUTURES",direction_mode="CALL")
    st.call_entry_lifecycles=[EntryBehavior(id="life",delay_bars=1)]
    entry="2026-01-01T00:10:00Z"
    result={"strategy":st.model_dump(),"trades":[{
        "direction":"LONG","entry_time":entry,"exit_time":"2026-01-01T00:20:00Z",
        "entry_lifecycle_id":"life","entry_lifecycle_signal_time":entry,
        "entry_lifecycle_age_bars":1,"entry_lifecycle_delay_bars":1,
        "entry_lifecycle_entries_before":0,"entry_lifecycle_max_entries":1,
        "entry_lifecycle_expired":False,"entry_lifecycle_eligible":True,
    }]}
    source=[{"time":1767225900,"call":{"life":True},"put":{}},
            {"time":1767226200,"call":{"life":True},"put":{}},
            {"time":1767226500,"call":{"life":True},"put":{}}]
    out=independently_replay_lifecycles(result,source,5)
    assert out["failures"]==[],out
    assert out["checked"]==1


def test_independent_lifecycle_replay_catches_falsified_age():
    from app.futures_lifecycle_replay import independently_replay_lifecycles
    from app.models import StrategyConfig, EntryBehavior
    st=StrategyConfig(market_type="FUTURES",direction_mode="CALL")
    st.call_entry_lifecycles=[EntryBehavior(id="life",delay_bars=1)]
    result={"strategy":st.model_dump(),"trades":[{
        "direction":"LONG","entry_time":"2026-01-01T00:10:00Z","exit_time":"2026-01-01T00:20:00Z",
        "entry_lifecycle_id":"life","entry_lifecycle_age_bars":4,
        "entry_lifecycle_delay_bars":1,"entry_lifecycle_entries_before":0,
        "entry_lifecycle_max_entries":1,"entry_lifecycle_expired":False,
        "entry_lifecycle_eligible":True,
    }]}
    source=[{"time":1767225900,"call":{"life":True},"put":{}},
            {"time":1767226200,"call":{"life":True},"put":{}},
            {"time":1767226500,"call":{"life":True},"put":{}}]
    out=independently_replay_lifecycles(result,source,5)
    assert any("entry_lifecycle_age_bars" in x for x in out["failures"])
