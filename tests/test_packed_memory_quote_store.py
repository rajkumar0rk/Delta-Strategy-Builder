"""Lossless packed-memory quote storage and quote capture/replay parity."""
from types import SimpleNamespace
import csv
import math

import pytest

from backtest import ema_vwap_research as legacy
from backtest.data import timestamp_ns
from backtest.packed_memory_quote_store import PackedMemoryQuoteStore
from backtest.positional_quote_capture import capture_quotes_positional


def _quote(n):
    return {
        "timestamp_ns": float(n), "bid": 0.25 + n,
        "ask": 0.75 + n, "bid_size": 0.0, "ask_size": 2.25,
        "volume": 0.0, "open_interest": 0.0,
    }


def test_packed_view_exact_order_index_slicing_and_cleanup():
    store = PackedMemoryQuoteStore()
    view = store.view(101)
    other = store.view(102)
    try:
        assert not view and len(view) == 0
        for i in range(11):
            store.append(101, _quote(i))
        store.append(102, _quote(100))
        assert list(view) == [_quote(i) for i in range(11)]
        assert list(reversed(view)) == [_quote(i) for i in reversed(range(11))]
        assert view[-1] == _quote(10)
        assert view[3] == _quote(3)
        assert list(view[2:10:3]) == [_quote(i) for i in (2, 5, 8)]
        assert list(view[::-3]) == [_quote(i) for i in (10, 7, 4, 1)]
        assert list(other) == [_quote(100)]
        assert store.snapshot_metrics() == {
            "payload_encoding": "PACKED_MEMORY",
            "captured_quote_rows": 12,
            "event_count": 2,
            "packed_payload_bytes": 12 * 56,
        }
        with pytest.raises(IndexError):
            _ = view[11]
        with pytest.raises(IndexError):
            _ = view[-12]
        with pytest.raises(TypeError):
            _ = view["bad"]
    finally:
        store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.view(10)
    with pytest.raises(RuntimeError, match="closed"):
        store.append(101, _quote(0))
    with pytest.raises(RuntimeError, match="closed"):
        store.snapshot_metrics()


def test_packed_schema_and_quote_limit_fail_closed():
    store = PackedMemoryQuoteStore(max_captured=1)
    try:
        with pytest.raises(ValueError, match="PACKED_QUOTE_SCHEMA_MISMATCH"):
            store.append(3, {"bid": 1.0})
        assert store.total == 0
        store.append(3, _quote(1))
        with pytest.raises(ValueError, match="CAPTURED_QUOTE_LIMIT_EXCEEDED"):
            store.append(3, _quote(2))
        assert store.total == 1
        assert store.view(3)[0] == _quote(1)
    finally:
        store.close()
    with pytest.raises(ValueError):
        PackedMemoryQuoteStore(max_captured=0)


def test_exact_float_and_nonfinite_bits_round_trip():
    store = PackedMemoryQuoteStore()
    quote = _quote(0)
    quote["timestamp_ns"] = float(1_779_999_000_000_000_000)
    quote["bid"] = math.nextafter(2.0, 3.0)
    quote["ask"] = float("inf")
    quote["bid_size"] = -0.0
    quote["volume"] = float("nan")
    try:
        store.append(1, quote)
        found = store.view(1)[0]
        assert found["timestamp_ns"] == quote["timestamp_ns"]
        assert found["bid"] == quote["bid"]
        assert math.isinf(found["ask"])
        assert math.copysign(1, found["bid_size"]) == -1
        assert math.isnan(found["volume"])
    finally:
        store.close()


def _event(symbol, timestamp):
    return SimpleNamespace(
        option=SimpleNamespace(
            symbol=symbol,
            expiration_ns=timestamp_ns("2026-09-02T00:00:00Z"),
        ),
        timestamp_ns=timestamp,
        quotes=[],
    )


def test_positional_capture_lists_equal_packed_views(tmp_path):
    start = timestamp_ns("2026-09-01T00:00:00Z")
    file = tmp_path / "quotes.csv"
    with file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "timestamp", "symbol", "bid", "ask",
            "bid_size", "ask_size", "volume", "open_interest",
        ])
        writer.writeheader()
        for minute in range(1, 9):
            writer.writerow({
                "timestamp": f"2026-09-01T00:{minute:02d}:00Z",
                "symbol": "BTC-CE" if minute < 6 else "BTC-PE",
                "bid": 1.1 + minute, "ask": 1.3 + minute,
                "bid_size": 3.0, "ask_size": 5.0, "volume": 20.0,
                "open_interest": 10.0,
            })
    original = [_event("BTC-CE", start), _event("BTC-PE", start)]
    compact = [_event("BTC-CE", start), _event("BTC-PE", start)]
    capture_quotes_positional(file, original)
    store = PackedMemoryQuoteStore()
    try:
        capture_quotes_positional(file, compact, quote_store=store)
        assert [list(e.quotes) for e in compact] == [e.quotes for e in original]
        assert store.total == sum(len(e.quotes) for e in original)
    finally:
        store.close()


def test_packed_mode_is_explicit_opt_in():
    from inspect import signature
    assert signature(legacy.run_dataset).parameters["quote_capture_storage"].default == "MEMORY"
