from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from app.data_store import DataStore
from app.engine import _select_option, chart_payload, run_backtest
from app.models import BacktestRequest, Condition, EntryBehavior, PreviewRequest, RuleGroup, StrategyConfig


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
    _seed(tmp_path, monkeypatch, expiration='2026-01-01T00:13:00Z')
    store=DataStore()
    parts=[store.resolve('sample')]
    store.ensure_indexes(parts)
    inst=store.load_instruments_many(parts)
    s=_strategy()
    _,quote,why=_select_option(store,parts,inst,pd.Timestamp('2026-01-01T00:11:00Z'),
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
