import csv
from dataclasses import dataclass
from pathlib import Path
import pytest
from app.broker_history import replay_broker_account, read_observed_account

@dataclass
class Part:
    root:Path

def write(path,rows):
    with path.open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

def snap(ts,**updates):
    d=dict(timestamp=ts,account_id='A',currency='USD',wallet_balance=100,im_w_ucf=30,
           mm_w_ucf=24,blocked_margin=30,risk_margin=30,margin_floor=10,ucf=0,
           commission=1,under_liquidation='false',source='DELTA_PORTFOLIO_MARGINS_CAPTURE')
    d.update(updates);return d

def fill(fid,ts,kind):
    return dict(fill_id=fid,timestamp=ts,account_id='A',currency='USD',
                product_symbol='C-BTC-100-010126',fill_type=kind,side='buy',
                size=1,price=10,commission=.1,source='DELTA_FILLS_HISTORY')

def test_missing_evidence_must_not_claim_liquidation_accuracy(tmp_path):
    r=replay_broker_account([Part(tmp_path)],'2026-01-01T00:00Z','2026-01-01T01:00Z',[])
    assert r['status']=='NO_RECORDS'
    assert r['execution_impact']=='NONE'
    assert r['hypothetical_liquidation_accuracy']=='NOT_VERIFIED'

def test_recorded_breaches_and_liquidation_and_settlement_price(tmp_path):
    write(tmp_path/'portfolio_margin_history.csv',[
        snap('2026-01-01T00:00Z'),snap('2026-01-01T00:05Z',blocked_margin=22,under_liquidation='true'),
        snap('2026-01-01T00:10Z',blocked_margin=30)])
    write(tmp_path/'account_fills_history.csv',[
        fill('one','2026-01-01T00:05Z','liquidation'),
        fill('two','2026-01-01T00:10Z','settlement')])
    t=[dict(id=1,symbol='C-BTC-100-010126',exit_reason='EXPIRY_SETTLEMENT',
            exit_time='2026-01-01T00:10Z',exit_price=10)]
    r=replay_broker_account([Part(tmp_path)],'2026-01-01T00:00Z','2026-01-01T00:10Z',t)
    assert r['snapshots']==3
    assert r['observed_breach_snapshots']==1
    assert r['liquidation_fills']==1
    assert r['settlement_checks'][0]['price_matches']
    assert not r['settlement_checks'][0]['net_pnl_comparable']

def test_no_future_snapshot_contaminates_earlier_range(tmp_path):
    write(tmp_path/'portfolio_margin_history.csv',[
        snap('2026-01-01T00:00Z'),snap('2026-01-01T00:10Z',blocked_margin=1)])
    r=replay_broker_account([Part(tmp_path)],'2026-01-01T00:00Z','2026-01-01T00:05Z',[])
    assert r['snapshots']==1
    assert r['observed_breach_snapshots']==0

def test_duplicate_conflict_and_invalid_source_fail_closed(tmp_path):
    write(tmp_path/'portfolio_margin_history.csv',[
        snap('2026-01-01T00:00Z'),snap('2026-01-01T00:00Z',blocked_margin=1)])
    with pytest.raises(ValueError,match='Conflicting'):
        read_observed_account([Part(tmp_path)])
    write(tmp_path/'portfolio_margin_history.csv',[snap('2026-01-01T00:00Z',source='FAKE')])
    with pytest.raises(ValueError,match='provenance'):
        read_observed_account([Part(tmp_path)])
