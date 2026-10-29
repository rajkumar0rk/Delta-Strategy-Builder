from __future__ import annotations
from app.futures_audit import audit_futures_parity


def sample():
    trade={'id':1,'direction':'LONG','entry_time':'2026-01-01T00:05:00Z',
           'exit_time':'2026-01-01T00:15:00Z','entry_price':101,
           'exit_price':110,'quantity':0.001,'entry_fee_usd':0.001,
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
