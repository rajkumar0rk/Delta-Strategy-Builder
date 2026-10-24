from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from app.data_store import DataStore
from app.engine import _select_option, chart_payload, run_backtest
from app.models import BacktestRequest, Condition, EntryBehavior, PreviewRequest, RuleGroup, SessionConfig, SessionWindow, StrategyConfig


def _csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _seed(tmp_path, monkeypatch, *, gap=False, expiration='2026-01-01T00:18:00Z'):
    root = tmp_path / 'data'
    part = root / 'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))
    ts = pd.date_range('2026-01-01T00:00:00Z', periods=8, freq='5min')
    bars = [dict(timestamp=t.isoformat(), open=100+i-.5, high=101+i,
                 low=99+i, close=100+i, volume=100) for i,t in enumerate(ts)]
    if gap:
        bars.pop(3)
    _csv(part/'underlying_bars.csv', bars)
    _csv(part/'option_instruments.csv', [dict(
        symbol='BTC100CE', source_symbol='BTC100CE', expiry='2026-01-01',
        strike=100, option_type='CE', activation='2025-12-31T00:00:00Z',
        expiration=expiration, price_precision=2, size_precision=0,
        price_increment=0.1, size_increment=1, lot_size=1,
        min_quantity=1, contract_value=0.001,
    )])
    quotes = [dict(timestamp=t.isoformat(), symbol='BTC100CE',
                   bid=10+i, ask=11+i, bid_size=100, ask_size=100,
                   volume=100, open_interest=100, source_event='fixture')
              for i,t in enumerate(ts)]
    _csv(part/'option_quotes.csv', quotes)
    return root


def _strategy():
    s = StrategyConfig(
        direction_mode='CALL', call_entry=RuleGroup(conditions=[
            Condition(id='trigger', left='close', operator='GT', value=99)]),
        call_entry_lifecycles=[EntryBehavior(id='delayed', trigger_condition_id='trigger',
                                             delay_bars=2)],
        put_entry=RuleGroup(),
    )
    s.option.min_dte_days = 0
    s.option.max_dte_days = 3
    s.option.max_spread_percent = 50
    s.risk.quantity = 1
    s.risk.stop_loss.mode = 'NONE'
    s.risk.take_profit.mode = 'NONE'
    s.risk.profit_protection.mode = 'NONE'
    s.risk.max_hold_minutes = None
    return s


def test_gap_policy_defaults_to_reject_but_allows_explicit_research_warning(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch,gap=True)
    st = _strategy()
    store = DataStore()
    store._bar_gap_policy = 'REQUIRE'
    report = store.preflight([store.resolve('sample')], '2026-01-01T00:00:00Z',
                             '2026-01-01T00:35:00Z', st)
    check = next(c for c in report['checks'] if c['name']=='Underlying 5m bars')
    assert check['missing'] == 1
    assert not report['ok']
    assert any('00:15:00' in v for v in check['missing_timestamps_sample'])
    store._bar_gap_policy = 'WARN'
    warned = store.preflight([store.resolve('sample')], '2026-01-01T00:00:00Z',
                             '2026-01-01T00:35:00Z', st)
    assert warned['ok']
    assert any('grid incomplete' in x for x in warned['warnings'])


def test_expired_first_quote_rejected_even_when_signal_precedes_expiry(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, expiration='2026-01-01T00:09:45Z')
    store=DataStore()
    parts=[store.resolve('sample')]
    store.ensure_indexes(parts)
    inst=store.load_instruments_many(parts)
    s=_strategy()
    _,quote,why=_select_option(store,parts,inst,pd.Timestamp('2026-01-01T00:09:30Z'),
                               100,'CALL',s)
    assert quote is None
    assert why == 'QUOTE_AT_OR_AFTER_EXPIRY'


def test_expiration_without_settlement_never_closes_at_post_expiry_quote(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch,expiration='2026-01-01T00:18:00Z')
    s=_strategy()
    result=run_backtest(BacktestRequest(
        dataset_id='sample',start='2026-01-01T00:00:00Z',
        end='2026-01-01T00:40:00Z',strategy=s))
    assert result['metrics']['trades']==0
    assert result['metrics']['unresolved_position_count']==1
    assert result['unresolved_position']['reason']=='EXPIRY_SETTLEMENT_UNAVAILABLE'


def test_chart_and_backtest_lifecycle_warmup_match_at_first_requested_bar(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch,expiration='2026-01-02T00:00:00Z')
    s=_strategy()
    start='2026-01-01T00:10:00Z'
    end='2026-01-01T00:40:00Z'
    result=run_backtest(BacktestRequest(dataset_id='sample',start=start,end=end,strategy=s))
    chart=chart_payload(PreviewRequest(dataset_id='sample',start=start,end=end,
                                      strategy=s,timeframe='5m'))
    first=next(x for x in chart['condition_states']
               if x['time']==int(pd.Timestamp(start).timestamp()))
    # The trigger has been active on two earlier closes, so delay_bars=2 is ready.
    assert first['call_delay_ready']
    assert first['call_activation_age_bars'] >= 2
    assert result['metrics']['trades'] >= 1
    assert result['trades'][0]['signal_time'].startswith('2026-01-01T00:10:00')



def test_chart_signal_matches_full_backtest_decision_log(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, expiration='2026-01-02T00:00:00Z')
    st = _strategy()
    st.execution.decision_log_mode = 'FULL'
    start = '2026-01-01T00:10:00Z'
    end = '2026-01-01T00:40:00Z'
    result = run_backtest(BacktestRequest(
        dataset_id='sample', start=start, end=end, strategy=st, storage_mode='FULL_DEBUG',
    ))
    chart = chart_payload(PreviewRequest(
        dataset_id='sample', start=start, end=end, strategy=st, timeframe='5m',
    ))
    scores = {pd.Timestamp(c['time'], unit='s', tz='UTC'): c
              for c in chart['condition_states']}
    with open(Path(result['result_dir'])/'decision_events.csv', newline='', encoding='utf-8') as handle:
        decisions = list(csv.DictReader(handle))
    entries = [r for r in decisions if r['direction']=='CALL' and r['kind']=='ENTRY']
    assert entries
    for row in entries:
        stamp = pd.Timestamp(row['timestamp'])
        assert stamp in scores
        chart_row = scores[stamp]
        assert float(row['passed_count']) == chart_row['call_passed_count']
        assert float(row['total']) == chart_row['call_total']


def test_time_stop_does_not_attempt_post_expiry_quote(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, expiration='2026-01-01T00:18:00Z')
    st = _strategy()
    st.risk.max_hold_minutes = 10
    result = run_backtest(BacktestRequest(
        dataset_id='sample', start='2026-01-01T00:00:00Z',
        end='2026-01-01T00:40:00Z', strategy=st,
    ))
    assert result['unresolved_position']['reason'] == 'EXPIRY_SETTLEMENT_UNAVAILABLE'
    assert result['metrics']['trades'] == 0

def test_imported_settlement_closes_with_observed_payoff_and_fee(tmp_path, monkeypatch):
    root=_seed(tmp_path,monkeypatch,expiration='2026-01-01T00:18:00Z')
    _csv(root/'sample'/'option_settlements.csv',[dict(
        symbol='BTC100CE',expiration='2026-01-01T00:18:00Z',
        settlement_price=7.5,index_twap=107.0,source='DELTA_EXPIRED_PRODUCTS')])
    st=_strategy()
    result=run_backtest(BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',
                                        end='2026-01-01T00:40:00Z',strategy=st))
    assert result['metrics']['verified_expiry_settlements']==1
    assert result['metrics']['trades']==1
    trade=result['trades'][0]
    assert trade['exit_reason']=='EXPIRY_SETTLEMENT'
    assert trade['exit_price']==pytest.approx(7.5)
    assert trade['settlement_fee_notional_source']=='INDEX_TWAP'
    assert trade['exit_time']=='2026-01-01T00:18:00+00:00'
    assert result['unresolved_position'] is None


def test_missing_or_conflicting_settlements_never_fabricate_price(tmp_path, monkeypatch):
    from app.settlement import load_option_settlements
    root=_seed(tmp_path,monkeypatch,expiration='2026-01-01T00:18:00Z')
    store=DataStore()
    assert load_option_settlements([store.resolve('sample')]) == {}
    _csv(root/'sample'/'option_settlements.csv',[
        dict(symbol='BTC100CE',expiration='2026-01-01T00:18:00Z',
             settlement_price=2,source='DELTA_EXPIRED_PRODUCTS'),
        dict(symbol='BTC100CE',expiration='2026-01-01T00:18:00Z',
             settlement_price=3,source='DELTA_EXPIRED_PRODUCTS'),
    ])
    with pytest.raises(ValueError,match='Conflicting'):
        load_option_settlements([store.resolve('sample')])


def test_session_end_exit_is_opt_in_and_not_a_fabricated_quote(tmp_path, monkeypatch):
    _seed(tmp_path,monkeypatch,expiration='2026-01-02T00:00:00Z')
    st=_strategy()
    st.risk.close_at_session_end=True
    st.session = SessionConfig(timezone='UTC', windows=[SessionWindow(start='00:00', end='00:15')])
    result=run_backtest(BacktestRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',
                                        end='2026-01-01T00:35:00Z',strategy=st))
    assert result['metrics']['session_end_exits']==1
    assert result['trades'][0]['exit_reason']=='SESSION_END_EXIT'
    # The opt-in session boundary must use a real pre-expiry quote.
    assert result['trades'][0]['exit_time']=='2026-01-01T00:15:00+00:00'
    assert result['metrics']['session_end_unfilled_attempts']==0


def test_margin_account_audit_is_read_only(tmp_path,monkeypatch):
    from app.settlement import load_margin_audit, audit_margin_observation
    root=_seed(tmp_path,monkeypatch,expiration='2026-01-02T00:00:00Z')
    _csv(root/'sample'/'account_margin_snapshots.csv',[dict(
        timestamp='2026-01-01T00:05:00Z',symbol='BTC100CE',
        initial_margin_usd=75,maintenance_margin_usd=60,
        account_equity_usd=150,source='DELTA_ACCOUNT_EXPORT')])
    from app.margin import short_margin_details
    from app.models import SellMarginConfig
    store=DataStore()
    observed=load_margin_audit([store.resolve('sample')])
    config=SellMarginConfig(enabled=True,margin_mode='PORTFOLIO_ESTIMATE',
                            initial_margin_percent=20,maintenance_margin_percent=10)
    estimate=short_margin_details(config,100000,1000,1,.001)
    audit=audit_margin_observation(observed,'BTC100CE','2026-01-01T00:06:00Z',estimate)
    assert audit is not None and not audit['comparable']
    assert audit['assumed_trade_initial_usd']==pytest.approx(20)
    assert audit['observed_account_initial_usd']==75



def test_session_end_does_not_open_on_final_eligible_candle(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, expiration='2026-01-02T00:00:00Z')
    st = _strategy()
    st.risk.close_at_session_end = True
    st.session = SessionConfig(timezone='UTC', windows=[SessionWindow(start='00:00', end='00:10')])
    result = run_backtest(BacktestRequest(
        dataset_id='sample', start='2026-01-01T00:00:00Z',
        end='2026-01-01T00:35:00Z', strategy=st,
    ))
    # Entry lifecycle is ready at 00:10, the last eligible candle.
    # No new trade may be opened when forced session close would be immediate.
    assert result['metrics']['trades'] == 0
    assert result['unresolved_position'] is None


def test_session_boundary_detection_handles_overlapping_and_overnight_windows():
    from app.engine import _session_end_due, _session_allowed
    c = SessionConfig(timezone='UTC', windows=[
        SessionWindow(start='23:30', end='00:15'),
        SessionWindow(start='00:10', end='00:30'),
    ])
    ts = pd.Timestamp('2026-01-02T00:15:00Z')
    assert _session_allowed(ts, c)
    assert not _session_end_due(ts, c, 5)
    assert _session_end_due(pd.Timestamp('2026-01-02T00:30:00Z'), c, 5)
