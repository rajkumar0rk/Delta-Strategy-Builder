"""Packed quote spool parity, bounded batches and temporary-file cleanup."""
from dataclasses import dataclass, field
from math import isnan
from types import SimpleNamespace

import pytest

from backtest.data import timestamp_ns
from backtest.event_quote_store import EventQuoteStore
from backtest.positional_quote_capture import capture_quotes_sweep_positional


def quote(i):
    return {
        "timestamp_ns": float(i), "bid": float(i + 1),
        "ask": float(i + 2), "bid_size": 1.0,
        "ask_size": 2.0, "volume": 3.0,
        "open_interest": 4.0,
    }


def test_packed_spool_matches_json_for_arbitrary_slice_and_replay(tmp_path):
    expected = {1: [], 2: []}
    json_store = EventQuoteStore(directory=tmp_path / "json", batch_size=3)
    packed = EventQuoteStore(directory=tmp_path / "packed", batch_size=3,
                             payload_encoding="PACKED")
    try:
        for i in range(25):
            for event_id in (1, 2):
                row = quote(i + event_id)
                json_store.append(event_id, row)
                packed.append(event_id, row)
                expected[event_id].append(row)
                assert len(packed._pending) < 3
        json_store.flush()
        packed.flush()
        for event_id in (1, 2):
            a = json_store.view(event_id)
            b = packed.view(event_id)
            assert list(a) == list(b) == expected[event_id]
            assert list(reversed(a)) == list(reversed(b))
            for index in (0, 1, -1, -10, 20):
                assert a[index] == b[index]
            for sl in (slice(None), slice(None,None,-1), slice(1,21,3),
                       slice(-2,-25,-2),slice(20,2,-3),slice(2,2)):
                assert a[sl] == b[sl]
        assert packed._con.execute(
            "SELECT MIN(length(payload)), MAX(length(payload)) FROM quotes"
        ).fetchone() == (56, 56)
        assert packed.total == 50
    finally:
        json_store.close()
        packed.close()
    assert not list((tmp_path / "json").iterdir())
    assert not list((tmp_path / "packed").iterdir())


def test_packed_schema_and_quota_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="payload_encoding"):
        EventQuoteStore(payload_encoding="UNKNOWN")
    store = EventQuoteStore(directory=tmp_path / "spool",
                            payload_encoding="PACKED", max_captured=1)
    try:
        with pytest.raises(ValueError,match="PACKED_QUOTE_SCHEMA_MISMATCH"):
            store.append(1, {"bid": 1.0})
        assert store.total == 0
        store.append(1,quote(7))
        with pytest.raises(ValueError,match="CAPTURED_QUOTE_LIMIT_EXCEEDED"):
            store.append(1,quote(8))
        assert store.total == 1
        store.flush()
        assert store.view(1)[0] == quote(7)
    finally:
        store.close()


@dataclass
class Event:
    timestamp_ns: int
    option: object
    quotes: object = field(default_factory=list)


def test_positional_sweep_capture_parity_with_packed_storage(tmp_path):
    start = timestamp_ns("2026-11-01T00:00:00Z")
    option = SimpleNamespace(symbol="BTC-CE",
                             expiration_ns=start+60*60*1_000_000_000)
    def events():
        return [Event(start,option),Event(start+60*1_000_000_000,option)]
    path = tmp_path / "quotes.csv"
    path.write_text(
        "timestamp,symbol,bid,ask,bid_size,ask_size,volume,open_interest\n"
        "2026-11-01T00:01:00Z,BTC-CE,5,6,10,10,3,7\n"
        "2026-11-01T00:02:00Z,BTC-CE,6,7,10,10,4,8\n"
        "2026-11-01T00:03:00Z,BTC-CE,7,8,10,10,5,9\n",
        encoding="utf-8",
    )
    store_json = EventQuoteStore(directory=tmp_path / "json",
                                  payload_encoding="JSON",batch_size=1)
    store_packed = EventQuoteStore(directory=tmp_path / "packed",
                                    payload_encoding="PACKED",batch_size=1)
    a,b = events(),events()
    try:
        capture_quotes_sweep_positional(path,a,quote_store=store_json)
        capture_quotes_sweep_positional(path,b,quote_store=store_packed)
        assert [list(e.quotes) for e in a] == [list(e.quotes) for e in b]
    finally:
        store_json.close()
        store_packed.close()
