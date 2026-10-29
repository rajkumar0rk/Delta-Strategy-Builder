from __future__ import annotations
import csv
import pandas as pd
import pytest
from pydantic import ValidationError
from app.data_store import DataStore
from app.engine import run_backtest
from app.futures_engine import _exit_level, _slipped, funding_events
from app.models import BacktestRequest, StrategyConfig, FuturesConfig, RuleGroup, Condition, EntryBehavior


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as out:
        writer=csv.DictWriter(out, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _seed(tmp_path, monkeypatch):
    root=tmp_path/'data'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path/'cache'))
    timestamps=pd.date_range('2026-01-01T00:00:00Z',periods=12,freq='5min')
    rows=[dict(timestamp=t.isoformat(),open=100+i,high=103+i,
               low=99+i,close=101+i,volume=100+i)
          for i,t in enumerate(timestamps)]
    _write(root/'sample'/'underlying_bars.csv',rows)
    return root


def _strategy():
    s=StrategyConfig(market_type='FUTURES',direction_mode='CALL',
                     call_entry=RuleGroup(conditions=[
                       Condition(id='entry',left='close',operator='GT',value=98)]),
                     call_entry_lifecycles=[EntryBehavior(id='long-one',delay_bars=0)])
    s.futures.funding_mode='EXCLUDE_WITH_WARNING'
    s.risk.max_hold_minutes=None
    s.futures.stop_loss_percent=1.5
    s.futures.take_profit_percent=1.5
    return s


def test_existing_option_strategies_default_to_options():
    assert StrategyConfig().market_type=='OPTIONS'
    assert FuturesConfig().symbol=='BTCUSD'
    with pytest.raises(ValidationError):
        FuturesConfig(leverage=200,maintenance_margin_percent=1)


def test_futures_preflight_does_not_need_option_files(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    store=DataStore()
    store._bar_gap_policy='REQUIRE'
    p=store.resolve('sample')
    assert p.instruments is None
    result=store.preflight([p],'2026-01-01T00:00:00Z','2026-01-01T01:00:00Z',_strategy())
    assert result['ok'],result['errors']
    assert not any('option' in e.lower() for e in result['errors'])


def test_long_futures_runs_without_option_quotes_and_preserves_fee_consistency(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert result['strategy']['market_type']=='FUTURES'
    assert result['metrics']['trades']>=1
    assert result['reliability']['grade']=='RESEARCH_ONLY'
    assert all(t['direction']=='LONG' for t in result['trades'])
    for trade in result['trades']:
        assert trade['fees_usd']==pytest.approx(trade['entry_fee_usd']+trade['exit_fee_usd'])
        assert trade['net_pnl_usd']==pytest.approx(
            trade['gross_pnl_usd']-trade['fees_usd']+trade['funding_usd'])
        assert pd.Timestamp(trade['exit_time'])>pd.Timestamp(trade['entry_time'])
    assert result['metrics']['net_pnl_usd']==pytest.approx(
        sum(t['net_pnl_usd'] for t in result['trades']))


def test_ambiguous_intrabar_stop_is_conservative():
    cfg=FuturesConfig(stop_loss_percent=1,take_profit_percent=1)
    pos=dict(entry_price=100,direction='LONG')
    row=type('Bar',(),dict(open=100,high=103,low=97))()
    assert _exit_level(pos,row,cfg)==('STOP_LOSS',99)
    pos['direction']='SHORT'
    assert _exit_level(pos,row,cfg)==('STOP_LOSS',101)
    assert _slipped(100,'LONG',True,2)>100
    assert _slipped(100,'SHORT',False,2)>100


def test_historical_funding_required_and_gaps_not_silently_zero(tmp_path,monkeypatch):
    root=_seed(tmp_path,monkeypatch)
    store=DataStore();parts=[store.resolve('sample')]
    with pytest.raises(ValueError,match='FUTURES_FUNDING_MISSING'):
        funding_events(parts,'2026-01-01T00:00:00Z','2026-01-01T00:55:00Z',required=True)
    _write(root/'sample'/'futures_funding.csv',[
        dict(timestamp='2026-01-01T00:00:00Z',symbol='BTCUSD',funding_rate='0.0001')])
    r,missing=funding_events(parts,'2026-01-01T00:00:00Z','2026-01-01T00:55:00Z',required=True)
    assert not missing and len(r)==1
    with pytest.raises(ValueError,match='FUTURES_FUNDING_GAP'):
        funding_events(parts,'2026-01-01T00:00:00Z','2026-01-01T08:05:00Z',required=True)


def test_missing_funding_can_be_explicitly_excluded(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.futures.funding_mode='EXCLUDE_WITH_WARNING'
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert result['futures_research']['funding_mode']=='EXCLUDE_WITH_WARNING'
    assert any('Funding excluded' in str(x) for x in result['reliability']['limitations'])


def test_short_execution_uses_directional_btc_pnl_without_option_instruments(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.direction_mode='PUT'
    s.put_entry=RuleGroup(conditions=[
        Condition(id='short_entry',left='close',operator='GT',value=98)])
    s.put_entry_lifecycles=[EntryBehavior(id='short-one',delay_bars=0)]
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert result['metrics']['trades']>=1
    assert all(t['direction']=='SHORT' for t in result['trades'])
    for trade in result['trades']:
        expected=(trade['entry_price']-trade['exit_price'])*trade['quantity']
        assert trade['gross_pnl_usd']==pytest.approx(expected)


def test_futures_rejects_underfunded_entries_instead_of_fabricating_leverage(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.risk.starting_balance_usd=.01
    s.futures.leverage=1
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert result['metrics']['trades']==0
    assert result['metrics']['insufficient_margin_rejections']>=1
    assert result['unresolved_position'] is None


def test_futures_slippage_rounds_adversely_to_valid_ticks():
    assert _slipped(100.1,'LONG',True,0,0.5)==100.5
    assert _slipped(100.1,'SHORT',True,0,0.5)==100.0
    assert _slipped(100.1,'LONG',False,0,0.5)==100.0
    assert _slipped(100.1,'SHORT',False,0,0.5)==100.5
    assert _slipped(100,'LONG',True,0,0.5,2)==101.0


def test_short_take_profit_rejects_impossible_negative_price():
    with pytest.raises(ValidationError):
        FuturesConfig(take_profit_percent=100)


def test_repeated_futures_signals_respect_one_entry_per_activation(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.call_entry_lifecycles=[EntryBehavior(id='one-per-trigger',max_entries_per_activation=1)]
    s.futures.stop_loss_percent=None
    s.futures.take_profit_percent=0.2
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert len(result['trades'])==1


def test_futures_legacy_config_still_validates_without_tick_fields():
    data=StrategyConfig(market_type='FUTURES').model_dump()
    data['futures'].pop('tick_size')
    data['futures'].pop('slippage_ticks')
    updated=StrategyConfig.model_validate(data)
    assert updated.futures.tick_size==0.5
    assert updated.futures.slippage_ticks==0


def test_futures_reports_candle_close_equity_without_overstating_realized_pnl(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.futures.stop_loss_percent=None
    s.futures.take_profit_percent=None
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    m=result['metrics']
    assert result['unresolved_position'] is not None
    assert result['unresolved_position']['estimated_unrealized_pnl_usd'] != 0
    assert m['estimated_final_equity_usd']==pytest.approx(result['equity_curve'][-1]['equity_usd'])
    assert m['estimated_candle_close_drawdown_percent']>=0
    assert m['max_mark_to_market_drawdown_usd'] is None
    times=[p['timestamp'] for p in result['equity_curve']]
    assert len(times)==len(set(times))
    assert m['net_pnl_usd']==sum(t['net_pnl_usd'] for t in result['trades'])


def test_underfunded_futures_events_are_not_all_risk_blocks(tmp_path,monkeypatch):
    _seed(tmp_path,monkeypatch)
    s=_strategy()
    s.risk.starting_balance_usd=.01
    s.futures.leverage=1
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',
        storage_mode='ANALYSIS',strategy=s))
    assert result['metrics']['insufficient_margin_rejections']>=1
    assert result['metrics']['rejection_reasons']['INSUFFICIENT_MARGIN']>=1
    assert result['decision_count']>=1
    assert (tmp_path/'results'/result['run_id']/'decision_events.csv.gz').is_file()


def test_published_btcusd_margin_tiers_and_order_cap():
    from app.futures_contract import (published_margin_percent, assumed_initial_margin_usd,
        assumed_maintenance_margin_usd, BTCUSD_SNAPSHOT)
    assert published_margin_percent(100_000,initial=True)==pytest.approx(.5)
    assert published_margin_percent(200_000,initial=True)==pytest.approx(.75)
    assert published_margin_percent(200_000,initial=False)==pytest.approx(.375)
    cfg=FuturesConfig(margin_tier_mode='DELTA_PUBLISHED_SNAPSHOT',leverage=200)
    assert assumed_initial_margin_usd(100_000,2,cfg)==pytest.approx(1500)
    assert assumed_maintenance_margin_usd(100_000,2,cfg)==pytest.approx(750)
    assert BTCUSD_SNAPSHOT['position_limit_usd']==5_000_000
    assert FuturesConfig().margin_tier_mode=='FLAT_RESEARCH'


def test_pre_2025_minute_funding_cannot_be_misread_as_eight_hour(tmp_path,monkeypatch):
    from app.futures_engine import funding_events
    _seed(tmp_path,monkeypatch)
    store=DataStore()
    parts=[store.resolve('sample')]
    with pytest.raises(ValueError,match='FUTURES_HISTORICAL_FUNDING_REGIME_UNSUPPORTED'):
        funding_events(parts,'2025-08-01T00:00:00Z','2025-08-02T00:00:00Z',required=True)
    rates,missing=funding_events(parts,'2025-08-01T00:00:00Z',
        '2025-08-02T00:00:00Z',required=False)
    assert rates=={} and missing==[]


def test_excluded_funding_never_applies_available_csv(tmp_path,monkeypatch):
    root=_seed(tmp_path,monkeypatch)
    _write(root/'sample'/'futures_funding.csv',[
        dict(timestamp='2026-01-01T00:00:00Z',symbol='BTCUSD',funding_rate='0.10')])
    store=DataStore()
    rates,missing=funding_events([store.resolve('sample')],
        '2026-01-01T00:00:00Z','2026-01-01T00:55:00Z',required=False)
    assert rates=={} and missing==[]
    s=_strategy()
    s.futures.funding_mode='EXCLUDE_WITH_WARNING'
    result=run_backtest(BacktestRequest(dataset_id='sample',
        start='2026-01-01T00:00:00Z',end='2026-01-01T01:00:00Z',strategy=s))
    assert result['metrics']['funding_usd']==0
    assert all(t['funding_usd']==0 for t in result['trades'])
