"""Opt-in futures 15m stop-market orders: no-lookahead, fixed SL/R, timing and compatibility."""
import csv

import pandas as pd
import pytest
from pydantic import ValidationError

from app.models import BacktestRequest, FuturesConfig, StrategyConfig
from app.futures_setups import PullbackBreakoutPlanner, risk_sized_lots
from app.engine import run_backtest


def _strategy(**overrides):
    pullback = {
        'enabled': True, 'setup_timeframe': '15m',
        'ema_indicator_id': 'ema20_15m', 'atr_indicator_id': 'atr14_15m',
        'require_volume': False, 'execution_mode': 'STOP_MARKET_INTRABAR',
        'stop_anchor': 'SIGNAL_CANDLE', 'breakout_buffer_ticks': 1,
        'max_wait_bars': 6, 'reward_r_multiple': 2,
        'stop_buffer_atr': .1, 'equity_risk_percent': .5,
    }
    pullback.update(overrides.pop('pullback', {}))
    spec = {
        'market_type': 'FUTURES', 'timeframe': '5m',
        'direction_mode': 'CALL', 'position_policy': 'EXCLUSIVE',
        'indicators': [
            {'id': 'ema20_15m', 'kind': 'EMA', 'timeframe': '15m',
             'params': {'period': 20}},
            {'id': 'atr14_15m', 'kind': 'ATR', 'timeframe': '15m',
             'params': {'period': 14}},
        ],
        'call_entry': {'conditions': [{'id': 'valid', 'left': 'close',
                                       'operator': 'GT', 'value': 0}]},
        'futures': {
            'stop_loss_percent': None, 'take_profit_percent': None,
            'funding_mode': 'EXCLUDE_WITH_WARNING',
            'force_exit_time': '23:45',
            'pullback': pullback,
        },
        'risk': {'starting_balance_usd': 100, 'max_hold_minutes': None,
                 'max_daily_loss_percent': 1},
        'session': {'timezone': 'Asia/Kolkata',
                    'windows': [{'start': '14:00', 'end': '21:59'}]},
    }
    for key, value in overrides.items():
        spec[key] = value
    return StrategyConfig.model_validate(spec)


def _dataset(tmp_path, monkeypatch, *, count=290, spike=112, high_after=102,
             low_on_spike=99):
    root = tmp_path / 'data'
    folder = root / 'sample'
    folder.mkdir(parents=True)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT', str(tmp_path / 'cache'))
    timestamps = pd.date_range('2026-01-01T00:05:00Z', periods=count, freq='5min')
    rows = []
    for i, ts in enumerate(timestamps):
        # Seed EMA20 with 20 neutral 15m candles, then create genuine
        # bullish 15m confirmations (close>EMA20 and close>open).
        bar = {'timestamp': ts.isoformat(), 'open': 100,
               'high': 102, 'low': 99, 'close': 100 if i < 60 else 101,
               'volume': 100}
        if i == spike:
            # A wick-only breach: 5m CLOSE NEVER confirms a breakout.
            bar['high'] = 105
            bar['low'] = low_on_spike
        if i == spike + 1:
            bar['high'] = high_after
            if high_after > 110:
                bar['low'] = 101
                bar['close'] = 115
        rows.append(bar)
    with (folder / 'underlying_bars.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return timestamps


def _run(tmp_path, monkeypatch, **kwargs):
    ts = _dataset(tmp_path, monkeypatch, **kwargs)
    return run_backtest(BacktestRequest(
        dataset_id='sample', start=ts[0].isoformat(),
        end=(ts[-1] + pd.Timedelta(minutes=5)).isoformat(),
        strategy=_strategy()))


def test_setup_candle_stop_is_frozen_and_available_without_swing_warmup():
    ts = pd.date_range('2026-01-01T00:05:00Z', periods=9, freq='5min')
    frame = pd.DataFrame([
        {'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 100,
         'ema20_15m': 100, 'atr14_15m': 4} for _ in ts], index=ts)
    cfg = FuturesConfig().pullback
    cfg.execution_mode = 'STOP_MARKET_INTRABAR'
    cfg.stop_anchor = 'SIGNAL_CANDLE'
    cfg.swing_lookback_bars = 10
    cfg.require_volume = False
    planner = PullbackBreakoutPlanner(frame, cfg, '5m')
    emitted = []
    for i, (timestamp, row) in enumerate(frame.iterrows()):
        assert planner.step(i, timestamp, row) == {}
        if planner.new_setups.get('LONG'):
            emitted.append(planner.new_setups['LONG'])
    assert emitted[0]['setup_index'] == 2
    assert emitted[0]['stop_price'] == pytest.approx(98.6)
    assert emitted[0]['level'] == 102


def test_intrabar_wick_trigger_uses_stop_market_and_fixed_2r(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, high_after=120)
    assert result['metrics']['stop_market_order_triggers'] >= 1
    assert result['metrics']['trades'] >= 1
    trade = result['trades'][0]
    assert trade['entry_fill_timing'] == 'INTRABAR_ESTIMATED'
    assert trade['pending_trigger_price'] > trade['setup_breakout_level']
    assert trade['entry_price'] >= trade['pending_trigger_price']
    assert trade['stop_price'] < trade['entry_price'] < trade['target_price']
    assert trade['exit_reason'] in ('TAKE_PROFIT', 'STOP_LOSS', 'FORCE_EXIT_CLOCK')
    assert trade['risk_per_lot_usd'] > 0
    assert trade['quantity'] > 0
    assert result['metrics']['cash_reconciliation_residual_usd'] == pytest.approx(0)


def test_force_exit_is_independent_of_entry_session(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, high_after=102)
    assert result['metrics']['trades'] >= 1
    trade = result['trades'][0]
    assert trade['exit_reason'] == 'FORCE_EXIT_CLOCK'
    assert pd.Timestamp(trade['exit_time']).tz_convert('Asia/Kolkata').strftime('%H:%M') == '23:45'
    assert trade['entry_time'] < trade['exit_time']


def test_risk_size_never_exceeds_remaining_daily_allowance():
    cfg = FuturesConfig()
    setup = cfg.pullback
    setup.equity_risk_percent = .5
    stop_fill = 99700
    lots, reason, per_lot = risk_sized_lots(
        100000, stop_fill, 'LONG', 100, cfg, setup, max_risk_usd=.2)
    assert lots * per_lot <= .2 + 1e-10
    if lots:
        assert (lots + 1) * per_lot > .2
    fixed = cfg.pullback.model_copy(update={'size_mode': 'FIXED'})
    fixed_lots, fixed_reason, _ = risk_sized_lots(
        100000, stop_fill, 'LONG', 100, cfg, fixed, max_risk_usd=.1)
    assert fixed_lots == 0
    assert fixed_reason == 'FIXED_SIZE_RISK_EXCEEDED'


def test_intraday_configuration_validates_1h_sources_and_clock():
    base = _strategy()
    assert base.futures.force_exit_time == '23:45'
    assert base.futures.pullback.max_wait_bars == 6
    with pytest.raises(ValidationError, match='force_exit_time'):
        _strategy(futures={'force_exit_time': '24:60'})
    with pytest.raises(ValidationError, match='trend requires'):
        _strategy(pullback={'trend_fast_ema_id': 'ema50_1h'})
    assert FuturesConfig().pullback.execution_mode == 'CLOSE_CONFIRM_NEXT_OPEN'
    assert FuturesConfig().pullback.stop_anchor == 'SWING'


def test_same_five_minute_bar_entry_and_stop_is_conservative(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, low_on_spike=95)
    assert result['metrics']['trades'] >= 1
    trade = result['trades'][0]
    assert trade['entry_fill_timing'] == 'INTRABAR_ESTIMATED'
    assert trade['exit_reason'] == 'STOP_LOSS'
    assert trade['net_pnl_usd'] < 0


def test_planner_aggregation_once_and_bounded_state(monkeypatch):
    from app import futures_setups
    times = pd.date_range('2026-01-01T00:05:00Z', periods=2040, freq='5min')
    frame = pd.DataFrame({
        'open': 100, 'high': 102, 'low': 99, 'close': 101,
        'volume': 100, 'ema20_15m': 100, 'atr14_15m': 4,
    }, index=times)
    cfg = FuturesConfig().pullback
    cfg.execution_mode = 'STOP_MARKET_INTRABAR'
    cfg.stop_anchor = 'SIGNAL_CANDLE'
    cfg.swing_lookback_bars = 3
    cfg.max_wait_bars = 6
    original = futures_setups._aggregate_completed
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(futures_setups, '_aggregate_completed', counted)
    planner = PullbackBreakoutPlanner(frame, cfg, '5m')
    for i, (ts, row) in enumerate(frame.iterrows()):
        planner.step(i, ts, row)
        assert len(planner.history) <= cfg.swing_lookback_bars
        assert len(planner.setups) <= 2
        assert len(planner.new_setups) <= 2
    assert len(calls) == 1  # no full-dataframe regrouping per candle
