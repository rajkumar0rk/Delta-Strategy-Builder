"""Exact quote payload/order parity for positional versus legacy DictReader."""
from dataclasses import replace
from pathlib import Path

import pytest

from backtest.ema_vwap_research import (
    SignalEvent, capture_quotes, capture_quotes_sweep,
)
from backtest.positional_quote_capture import (
    capture_quotes_positional, capture_quotes_sweep_positional,
)
from backtest.data import OptionSpec, timestamp_ns


def _option(symbol):
    return OptionSpec(
        symbol=symbol, source_symbol=symbol, expiry="01DEC26",
        strike=100000.0, option_type="CE",
        activation_ns=timestamp_ns("2026-11-01T00:00:00Z"),
        expiration_ns=timestamp_ns("2026-12-01T00:00:00Z"),
        price_precision=1, size_precision=0, price_increment=0.1,
        size_increment=1, lot_size=1, min_quantity=1, contract_value=0.001,
    )


def _events():
    return [
        SignalEvent(timestamp_ns("2026-11-02T00:00:00Z"), "CALL", 100000, _option("A"), []),
        SignalEvent(timestamp_ns("2026-11-02T00:01:00Z"), "CALL", 100000, _option("A"), []),
        SignalEvent(timestamp_ns("2026-11-02T00:00:00Z"), "CALL", 100000, _option("B"), []),
    ]


@pytest.mark.parametrize("sweep", [False, True])
@pytest.mark.parametrize("horizon", [None, 1, 10])
def test_positional_capture_matches_original(tmp_path, sweep, horizon):
    path = tmp_path / "quotes.csv"
    path.write_text(
        "symbol,timestamp,bid,ask,bid_size,ask_size,volume,open_interest\n"
        "Z,2026-11-02T00:00:00Z,10,11,1,2,1,2\n"
        "A,2026-11-02T00:00:00Z,10,11,1,2,1,2\n"
        "A,2026-11-02T00:01:00Z,10.5,11.5,,,,\n"
        "B,2026-11-02T00:01:30Z,12,13,1,2,3,4\n"
        "A,2026-11-02T00:02:00Z,11,12,3,4,5,6\n"
        "A,2026-11-02T00:03:00Z,13,14,5,6,7,8\n",
        encoding="utf-8",
    )
    original, fast = _events(), _events()
    old = capture_quotes_sweep if sweep else capture_quotes
    new = capture_quotes_sweep_positional if sweep else capture_quotes_positional
    old(path, original, horizon_minutes=horizon)
    new(path, fast, horizon_minutes=horizon)
    assert [item.quotes for item in fast] == [item.quotes for item in original]


@pytest.mark.parametrize("sweep", [False, True])
def test_short_rows_and_optional_columns_match_original(tmp_path, sweep):
    path = tmp_path / "quotes.csv"
    path.write_text(
        "timestamp,symbol,bid,ask\n"
        "2026-11-02T00:01:00Z,A,10,11\n"
        "2026-11-02T00:02:00Z,A,12,13\n",
        encoding="utf-8",
    )
    original, fast = _events(), _events()
    (capture_quotes_sweep if sweep else capture_quotes)(path, original)
    (capture_quotes_sweep_positional if sweep else capture_quotes_positional)(path, fast)
    assert [item.quotes for item in fast] == [item.quotes for item in original]


def test_sweep_rejects_out_of_order(tmp_path):
    path = tmp_path / "quotes.csv"
    path.write_text(
        "symbol,timestamp,bid,ask\n"
        "A,2026-11-02T00:02:00Z,1,2\n"
        "A,2026-11-02T00:01:00Z,1,2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="QUOTE_TIMESTAMP_OUT_OF_ORDER"):
        capture_quotes_sweep_positional(path, _events())
