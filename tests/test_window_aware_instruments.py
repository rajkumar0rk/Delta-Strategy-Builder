"""Verify pruning cannot change eligible option selection inside the window."""
import csv
from datetime import datetime, timedelta, timezone

import pytest

from backtest.data import timestamp_ns
from backtest.ema_vwap_research import _option_specs, _select_option


def _make_csv(path):
    header = [
        "symbol", "source_symbol", "expiry", "strike", "option_type",
        "activation", "expiration", "price_precision", "size_precision",
        "price_increment", "size_increment", "lot_size", "min_quantity",
        "contract_value",
    ]
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rows = []
    for day in (-9, -3, 0, 1, 2, 5, 9):
        for side in ("CE", "PE"):
            for strike in (98000, 100000, 102000):
                activation = base + timedelta(days=day)
                expiry = activation + timedelta(days=3)
                symbol = f"BTC-{day}-{strike}-{side}"
                rows.append([
                    symbol, symbol, expiry.isoformat(), strike, side,
                    activation.isoformat(), expiry.isoformat(),
                    1, 0, 0.5, 1, 1, 1, 0.001,
                ])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return base


def test_pruned_selection_parity_for_every_signal(tmp_path):
    path = tmp_path / "option_instruments.csv"
    base = _make_csv(path)
    start = timestamp_ns(base.isoformat())
    end = timestamp_ns((base + timedelta(days=5)).isoformat())
    original = _option_specs(path)
    selected = _option_specs(path, active_start_ns=start, active_end_ns=end)
    assert 0 < len(selected) < len(original)
    for day in (0, 1, 2, 3, 4):
        for hour in (0, 6, 12, 18):
            stamp = timestamp_ns((base + timedelta(days=day, hours=hour)).isoformat())
            for side in ("CALL", "PUT"):
                for spot in (97000.0, 100000.0, 103000.0):
                    old = _select_option(
                        original, stamp, side, spot,
                        min_days_to_expiry=0, max_days_to_expiry=10
                    )
                    new = _select_option(
                        selected, stamp, side, spot,
                        min_days_to_expiry=0, max_days_to_expiry=10
                    )
                    assert new == old


def test_window_boundaries_and_incremental_admission(tmp_path):
    path = tmp_path / "option_instruments.csv"
    base = _make_csv(path)
    start = timestamp_ns(base.isoformat())
    end = timestamp_ns((base + timedelta(days=5)).isoformat())
    selected = _option_specs(path, active_start_ns=start, active_end_ns=end)
    assert all(item.activation_ns < end and item.expiration_ns > start for item in selected)
    with pytest.raises(ValueError, match="LEGACY_OPTION_INSTRUMENT_LIMIT_EXCEEDED"):
        _option_specs(path, active_start_ns=start, active_end_ns=end, max_instruments=1)
    with pytest.raises(ValueError, match="requires both bounds"):
        _option_specs(path, active_start_ns=start)
    with pytest.raises(ValueError, match="end must follow start"):
        _option_specs(path, active_start_ns=end, active_end_ns=start)
