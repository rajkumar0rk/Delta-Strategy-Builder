from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from app.data_store import DataStore
from app.engine import _new_result_dir, _quantity
from app.indicators import compute_indicators
from app.models import IndicatorInstance, StrategyConfig


def _write_csv(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _bars_frame(unit: str = 'ns') -> pd.DataFrame:
    # Close timestamps. 00:05..01:00 is the first complete UTC 1h candle,
    # 01:05..02:00 is the second.
    idx = pd.date_range('2026-01-01T00:00:00Z', periods=49, freq='5min')
    if hasattr(idx, 'as_unit'):
        idx = idx.as_unit(unit)
    close = pd.Series([100.0 + i for i in range(len(idx))], index=idx)
    return pd.DataFrame({
        'open': close - 0.25,
        'high': close + 1.0,
        'low': close - 1.0,
        'close': close,
        'volume': 100.0,
    }, index=idx)


def test_higher_timeframe_indicators_are_datetime_resolution_independent():
    indicator = IndicatorInstance(
        id='ema1h', kind='EMA', params={'period': 2, 'source': 'close'},
        chart_only=False, timeframe='1h',
    )
    ns, _ = compute_indicators(_bars_frame('ns'), [indicator], '5m')
    us, _ = compute_indicators(_bars_frame('us'), [indicator], '5m')
    ns_values = ns['ema1h'].astype(float)
    us_values = us['ema1h'].astype(float)
    assert ns_values.notna().any()
    assert us_values.notna().any()
    # Two complete UTC 1h candles are required for EMA(2), so the first value is 02:00.
    first_ns = ns_values.first_valid_index()
    first_us = us_values.first_valid_index()
    assert first_ns == pd.Timestamp('2026-01-01T02:00:00Z')
    assert first_us == pd.Timestamp('2026-01-01T02:00:00Z')
    assert ns_values.dropna().to_numpy() == pytest.approx(us_values.dropna().to_numpy())


def test_higher_timeframe_bars_do_not_change_when_from_time_changes(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    ds = root / 'sample'
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT', str(root))
    rows = []
    idx = pd.date_range('2025-12-31T23:45:00Z', '2026-01-01T01:00:00Z', freq='5min')
    for i, ts in enumerate(idx):
        close = 100.0 + i
        rows.append({
            'timestamp': ts.isoformat().replace('+00:00', 'Z'),
            'open': close - 0.5,
            'high': close + 1.0,
            'low': close - 1.0,
            'close': close,
            'volume': 10.0,
        })
    _write_csv(ds / 'underlying_bars.csv', ['timestamp','open','high','low','close','volume'], rows)

    store = DataStore()
    part = store.resolve('sample')
    a = store.load_bars(part, '2026-01-01T00:00:00Z', '2026-01-01T01:01:00Z', '10m')
    b = store.load_bars(part, '2026-01-01T00:05:00Z', '2026-01-01T01:01:00Z', '10m')
    common = a.index.intersection(b.index)
    assert list(common.strftime('%H:%M'))[:3] == ['00:10', '00:20', '00:30']
    pd.testing.assert_frame_equal(a.loc[common], b.loc[common])

    # Manually verify the 00:10 UTC bar is 00:05 + 00:10, not a range-start phase.
    source = pd.DataFrame(rows)
    r5 = source[source.timestamp == '2026-01-01T00:05:00Z'].iloc[0]
    r10 = source[source.timestamp == '2026-01-01T00:10:00Z'].iloc[0]
    bar = a.loc[pd.Timestamp('2026-01-01T00:10:00Z')]
    assert bar.open == pytest.approx(float(r5.open))
    assert bar.close == pytest.approx(float(r10.close))
    assert bar.high == pytest.approx(max(float(r5.high), float(r10.high)))
    assert bar.low == pytest.approx(min(float(r5.low), float(r10.low)))


def _spec(**overrides):
    base = {
        'contract_value': 1.0,
        'size_increment': 1.0,
        'min_quantity': 1.0,
    }
    base.update(overrides)
    return base


def test_budget_mode_can_reject_or_allow_minimum_quantity_above_budget():
    strategy = StrategyConfig(direction_mode='CALL')
    strategy.risk.quantity_mode = 'BUDGET'
    strategy.risk.budget_usd = 50.0
    strategy.risk.enforce_cash = True
    strategy.risk.enforce_trade_budget_strict = True
    qty, required, reason = _quantity(strategy, _spec(), 80.0, 100.0, 200.0, 'BUY')
    assert qty == 0
    assert required > 50
    assert reason == 'MIN_QUANTITY_EXCEEDS_BUDGET'

    strategy.risk.enforce_trade_budget_strict = False
    qty, required, reason = _quantity(strategy, _spec(), 80.0, 100.0, 200.0, 'BUY')
    assert qty == pytest.approx(1.0)
    assert required > 50
    assert reason is None


def test_fixed_quantity_always_obeys_minimum_and_size_increment():
    strategy = StrategyConfig(direction_mode='CALL')
    strategy.risk.quantity_mode = 'FIXED'
    strategy.risk.quantity = 15.0
    strategy.risk.enforce_trade_budget_strict = False
    qty, _, reason = _quantity(
        strategy,
        _spec(size_increment=10.0, min_quantity=10.0),
        1.0, 100.0, 1000.0, 'BUY',
    )
    assert qty == 0
    assert reason == 'INVALID_FIXED_QUANTITY'

    strategy.risk.quantity = 20.0
    qty, _, reason = _quantity(
        strategy,
        _spec(size_increment=10.0, min_quantity=10.0),
        1.0, 100.0, 1000.0, 'BUY',
    )
    assert qty == pytest.approx(20.0)
    assert reason is None


def test_result_directories_are_unique_even_for_same_strategy(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT', str(tmp_path / 'results'))
    id1, p1 = _new_result_dir('Same Strategy')
    id2, p2 = _new_result_dir('Same Strategy')
    assert id1 != id2
    assert p1 != p2
    assert p1.is_dir() and p2.is_dir()
