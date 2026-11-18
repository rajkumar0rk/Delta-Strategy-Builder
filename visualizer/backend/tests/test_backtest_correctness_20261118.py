"""Causal execution and reporting regressions for the V15.1 visualizer engine."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from app.data_store import DataStore
from app.engine import _chart_page, _quantity, _quote_ok, _select_candidates, _select_option, _warmup_start, run_backtest
from app.models import (
    BacktestRequest, Condition, IndicatorInstance, OptionSelection, RuleGroup,
    RiskConfig, StrategyConfig,
)


def test_strike_selected_before_expiry_when_front_strike_missing():
    ts = pd.Timestamp('2026-01-01T00:00:00Z')
    inst = pd.DataFrame([
        {'symbol': 'FRONT65000', 'activation': ts - pd.Timedelta(days=1),
         'expiration': ts + pd.Timedelta(days=1), 'option_type': 'CE', 'strike': 65000},
        {'symbol': 'LATER64600', 'activation': ts - pd.Timedelta(days=1),
         'expiration': ts + pd.Timedelta(days=2), 'option_type': 'CE', 'strike': 64600},
        {'symbol': 'LATER65000', 'activation': ts - pd.Timedelta(days=1),
         'expiration': ts + pd.Timedelta(days=2), 'option_type': 'CE', 'strike': 65000},
    ])
    ranked = _select_candidates(inst, ts, 64610, 'CALL', OptionSelection(min_dte_days=0, max_dte_days=3))
    assert ranked.iloc[0].symbol == 'LATER64600'


def test_crossed_and_zero_bid_quotes_are_not_accepted():
    cfg = OptionSelection(max_spread_percent=100)
    assert _quote_ok({'bid': 12, 'ask': 10}, cfg) == (False, 'INVALID_BID_ASK')
    assert _quote_ok({'bid': 0, 'ask': 10}, cfg) == (False, 'INVALID_BID_ASK')
    assert _quote_ok({'bid': 9, 'ask': 10}, cfg)[0]


def test_margin_estimate_blocks_unfunded_sells_without_inventing_venue_margin():
    cfg = StrategyConfig()
    cfg.risk.quantity = 1
    cfg.risk.budget_usd = 1000
    cfg.risk.require_sell_margin_estimate = True
    spec = {'contract_value': 1.0, 'size_increment': 1.0, 'min_quantity': 1.0}
    qty, _, why = _quantity(cfg, spec, 10.0, 100, 50, 'SELL')
    assert qty == 0 and why == 'SELL_MARGIN_ESTIMATE_REQUIRED'
    cfg.risk.sell_margin_per_contract_usd = 80
    qty, _, why = _quantity(cfg, spec, 10.0, 100, 50, 'SELL')
    assert qty == 0 and why == 'INSUFFICIENT_CASH'
    cfg.risk.sell_margin_per_contract_usd = 25
    qty, needed, why = _quantity(cfg, spec, 10.0, 100, 50, 'SELL')
    assert qty == 1 and why is None and needed > 25


def test_new_strategies_have_no_implicit_four_hour_exit():
    assert RiskConfig().max_hold_minutes is None


def test_warmup_loads_long_ema_history_before_requested_start():
    strategy = StrategyConfig(timeframe='5m', indicators=[
        IndicatorInstance(id='ema200', kind='EMA', timeframe='1h', params={'period': 200, 'source': 'close'})
    ])
    req = BacktestRequest(dataset_id='dummy', start='2026-07-01T00:00:00Z', end='2026-07-02T00:00:00Z', strategy=strategy)
    warmup = _warmup_start(req)
    assert pd.Timestamp(req.start) - pd.Timestamp(warmup) >= pd.Timedelta(hours=2000)


BAR_FIELDS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
INST_FIELDS = ['symbol', 'source_symbol', 'expiry', 'strike', 'option_type', 'activation',
               'expiration', 'price_precision', 'size_precision', 'price_increment',
               'size_increment', 'lot_size', 'min_quantity', 'contract_value']
QUOTE_FIELDS = ['timestamp', 'symbol', 'bid', 'ask', 'bid_size', 'ask_size', 'volume',
                'open_interest', 'source_event']


def _write(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as h:
        writer = csv.DictWriter(h, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sample(tmp_path, monkeypatch, quote_rows, lows=None):
    data = tmp_path / 'data'
    folder = data / 'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(data))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))
    closes = [100, 102, 105, 107, 109]
    bars = []
    for i, close in enumerate(closes):
        bars.append({
            'timestamp': f'2026-01-01T00:{i*5:02d}:00Z',
            'open': close - 0.5, 'high': close + 2,
            'low': (lows[i] if lows else close - 2), 'close': close, 'volume': 100,
        })
    _write(folder / 'underlying_bars.csv', BAR_FIELDS, bars)
    _write(folder / 'option_instruments.csv', INST_FIELDS, [{
        'symbol': 'BTC100CE', 'source_symbol': 'BTC100CE', 'expiry': '2026-01-02',
        'strike': 100, 'option_type': 'CE', 'activation': '2025-12-31T00:00:00Z',
        'expiration': '2026-01-02T00:00:00Z', 'price_precision': 2,
        'size_precision': 0, 'price_increment': 1, 'size_increment': 1,
        'lot_size': 1, 'min_quantity': 1, 'contract_value': 0.001,
    }])
    _write(folder / 'option_quotes.csv', QUOTE_FIELDS, [
        {'timestamp': t, 'symbol': 'BTC100CE', 'bid': bid, 'ask': ask,
         'bid_size': 100, 'ask_size': 100, 'volume': 100, 'open_interest': 1000,
         'source_event': 'test'} for t, bid, ask in quote_rows
    ])
    strategy = StrategyConfig(
        name='Causal-regression', direction_mode='CALL',
        call_entry=RuleGroup(conditions=[Condition(id='entry', left='close', operator='GT', value=100)]),
    )
    strategy.risk.stop_loss.mode = 'NONE'
    strategy.risk.take_profit.mode = 'NONE'
    strategy.risk.profit_protection.mode = 'NONE'
    strategy.risk.max_hold_minutes = None
    strategy.risk.quantity = 1
    strategy.option.min_dte_days = 0
    strategy.option.max_dte_days = 3
    strategy.option.max_spread_percent = 50
    return folder, strategy


def _run(strategy):
    req = BacktestRequest(
        dataset_id='sample', start='2026-01-01T00:00:00Z',
        end='2026-01-01T00:25:00Z', strategy=strategy,
    )
    return run_backtest(req)


def test_no_fake_same_quote_end_of_data_exit(tmp_path, monkeypatch):
    _, strategy = _sample(tmp_path, monkeypatch, [('2026-01-01T00:05:00Z', 10, 11)])
    result = _run(strategy)
    assert result['metrics']['trades'] == 0
    assert result['metrics']['open_positions_at_end'] == 1
    assert result['unresolved_exposure']['reason'] == 'END_OF_DATA_UNCLOSED'


def test_quote_mtm_drawdown_is_visible_even_if_completed_trade_wins(tmp_path, monkeypatch):
    _, strategy = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:05:00Z', 10, 11),
        ('2026-01-01T00:10:00Z', 2, 3),
        ('2026-01-01T00:15:00Z', 14, 15),
        ('2026-01-01T00:24:30Z', 14, 15),
    ])
    result = _run(strategy)
    assert result['metrics']['trades'] == 1
    assert result['trades'][0]['net_pnl_usd'] > 0
    assert result['metrics']['max_mark_to_market_drawdown_usd'] > 0
    assert result['metrics']['max_closed_trade_drawdown_usd'] == 0


def test_partial_first_stop_candle_does_not_assume_preentry_wick(tmp_path, monkeypatch):
    _, strategy = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:05:30Z', 10, 11),
        ('2026-01-01T00:15:00Z', 12, 13),
        ('2026-01-01T00:24:30Z', 12, 13),
    ], lows=[98, 100, 70, 106, 108])
    strategy.risk.stop_loss.mode = 'UNDERLYING_SIGNAL_CANDLE'
    strategy.risk.stop_loss.signal_candle_trigger = 'WICK'
    strategy.risk.stop_loss.signal_candle_execution_timeframe = '5m'
    result = _run(strategy)
    assert result['metrics']['trades'] == 1
    assert result['trades'][0]['exit_reason'] == 'END_OF_DATA'


def test_invalid_quote_is_skipped_for_next_valid_quote(tmp_path, monkeypatch):
    folder, _ = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:05:00Z', 12, 10),
        ('2026-01-01T00:05:30Z', 9, 10),
    ])
    store = DataStore()
    part = store.resolve('sample')
    try:
        store.ensure_index(part)
        quote = store.first_quote(part, 'BTC100CE', '2026-01-01T00:05:00Z', 90)
        assert quote is not None
        assert quote['timestamp'].startswith('2026-01-01T00:05:30')
        assert quote['bid'] == 9
    finally:
        store.close()


def test_saved_strategy_can_be_loaded_from_project_folder(tmp_path, monkeypatch):
    from app.main import load_strategy, save_strategy
    from app.models import SaveStrategyRequest
    monkeypatch.setenv('STRATEGY_LAB_PROJECT_ROOT', str(tmp_path))
    saved = save_strategy(SaveStrategyRequest(strategy=StrategyConfig(name='Strategy load smoke')))
    assert Path(saved['path']).exists()
    loaded = load_strategy('strategy-load-smoke')
    assert loaded['strategy']['name'] == 'Strategy load smoke'


def test_option_execution_cannot_fill_after_replay_end_or_contract_expiry():
    ts = pd.Timestamp('2026-01-01T00:05:00Z')
    class LateQuote:
        def first_quote_many(self, parts, symbol, at, seconds):
            return {
                'timestamp': '2026-01-01T00:05:30Z', 'bid': 9.0, 'ask': 10.0,
                'volume': 100, 'open_interest': 1000,
            }
    strategy = StrategyConfig()
    strategy.option.min_dte_days = 0
    strategy.option.max_dte_days = 3
    strategy.option.max_spread_percent = 50
    inst = pd.DataFrame([{
        'symbol': 'CE', 'activation': ts - pd.Timedelta(days=1),
        'expiration': ts + pd.Timedelta(days=1), 'option_type': 'CE',
        'strike': 100,
    }])
    spec, quote, why = _select_option(
        LateQuote(), [], inst, ts, 100, 'CALL', strategy,
        backtest_end='2026-01-01T00:05:10Z',
    )
    assert spec is None and quote is None and why == 'QUOTE_AFTER_BACKTEST_END'
    inst.loc[0, 'expiration'] = ts + pd.Timedelta(seconds=20)
    spec, quote, why = _select_option(
        LateQuote(), [], inst, ts, 100, 'CALL', strategy,
        backtest_end='2026-01-01T00:06:00Z',
    )
    assert spec is None and quote is None and why == 'CONTRACT_EXPIRED_AT_FILL'


def test_terminal_exit_rejects_quote_stale_by_hours(tmp_path, monkeypatch):
    _, strategy = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:05:00Z', 10, 11),
        ('2026-01-01T00:10:00Z', 12, 13),
    ])
    result = _run(strategy)
    assert result['metrics']['trades'] == 0
    assert result['metrics']['open_positions_at_end'] == 1
    assert result['unresolved_exposure']['reason'] == 'END_OF_DATA_UNCLOSED'


def test_last_tail_option_quote_still_triggers_stop(tmp_path, monkeypatch):
    _, strategy = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:05:00Z', 10, 11),
        ('2026-01-01T00:22:00Z', 2, 3),
    ])
    strategy.risk.stop_loss.mode = 'OPTION_PERCENT'
    strategy.risk.stop_loss.value = 15
    result = _run(strategy)
    assert result['metrics']['trades'] == 1
    assert result['trades'][0]['exit_reason'] == 'STOP_LOSS'
    assert result['trades'][0]['exit_time'].startswith('2026-01-01T00:22:00')


def test_sell_margin_guard_not_bypassed_by_enforce_cash_false():
    config = StrategyConfig(call_action='SELL')
    config.risk.require_sell_margin_estimate = True
    config.risk.sell_margin_per_contract_usd = 75
    config.risk.enforce_cash = False
    config.risk.quantity = 1
    config.risk.budget_usd = 1000
    spec = {'contract_value': 1, 'size_increment': 1, 'min_quantity': 1}
    qty, _, reason = _quantity(config, spec, 10, 100, 50, 'SELL')
    assert qty == 0 and reason == 'INSUFFICIENT_CASH'


def test_chart_pagination_keeps_candles_contiguous_without_synthetic_ohlc():
    frame = pd.DataFrame({'close': list(range(61001))},
                         index=pd.date_range('2025-01-01', periods=61001, freq='5min', tz='UTC'))
    last, meta = _chart_page(frame, 0)
    middle, middle_meta = _chart_page(frame, 30000)
    first, first_meta = _chart_page(frame, 60000)
    assert len(last) == len(middle) == 30000 and len(first) == 1001
    assert last.iloc[0].close == 31001
    assert middle.iloc[0].close == 1001
    assert middle.iloc[-1].close + 1 == last.iloc[0].close
    assert first.iloc[-1].close + 1 == middle.iloc[0].close
    assert meta['has_older'] and not meta['has_newer']
    assert middle_meta['has_older'] and middle_meta['has_newer']
    assert not first_meta['has_older'] and first_meta['has_newer']


def test_final_five_minute_underlying_wick_stop_after_last_ten_minute_strategy_candle(tmp_path, monkeypatch):
    folder, strategy = _sample(tmp_path, monkeypatch, [
        ('2026-01-01T00:10:00Z', 10, 11),
        ('2026-01-01T00:25:20Z', 8, 9),
    ])
    # 00:20 is the final completed 10m strategy candle. The 00:25
    # underlying candle is complete and must still trigger a frozen stop.
    bars = pd.read_csv(folder / 'underlying_bars.csv')
    bars = pd.concat([bars, pd.DataFrame([{
        'timestamp': '2026-01-01T00:25:00Z',
        'open': 108, 'high': 109, 'low': 90, 'close': 107,
        'volume': 100,
    }])], ignore_index=True)
    bars.to_csv(folder / 'underlying_bars.csv', index=False)
    strategy.timeframe = '10m'
    strategy.risk.stop_loss.mode = 'UNDERLYING_SIGNAL_CANDLE'
    strategy.risk.stop_loss.signal_candle_trigger = 'WICK'
    strategy.risk.stop_loss.signal_candle_execution_timeframe = '5m'
    result = run_backtest(BacktestRequest(
        dataset_id='sample', start='2026-01-01T00:00:00Z',
        end='2026-01-01T00:26:00Z', strategy=strategy,
    ))
    assert result['metrics']['trades'] == 1
    assert result['trades'][0]['exit_reason'] == 'UNDERLYING_SIGNAL_CANDLE_STOP'
    assert result['trades'][0]['exit_time'].startswith('2026-01-01T00:25:20')
