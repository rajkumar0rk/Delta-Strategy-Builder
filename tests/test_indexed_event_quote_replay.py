"""Parity and index coverage for SQLite event-local quote replay."""
import pytest

from backtest.event_quote_store import EventQuoteStore


def test_interleaved_event_quotes_preserve_all_sequence_operations(tmp_path):
    expected = {11: [], 22: [], 33: []}
    store = EventQuoteStore(directory=tmp_path / "spool", batch_size=7)
    try:
        for i in range(31):
            for event_id in (33, 11, 22):
                payload = {"bid": float(event_id + i), "timestamp_ns": float(i)}
                expected[event_id].append(payload)
                store.append(event_id, payload)
        store.flush()
        for event_id, source in expected.items():
            view = store.view(event_id)
            assert len(view) == len(source)
            assert list(view) == source
            assert list(reversed(view)) == list(reversed(source))
            for index in (0, 1, 7, len(source) - 1, -1, -7, -len(source)):
                assert view[index] == source[index]
            for selection in (
                slice(None), slice(None, None, -1), slice(1, 20),
                slice(0, 25, 3), slice(20, 1, -3),
                slice(-2, -30, -4), slice(20, 2), slice(3, 3),
                slice(100, 200), slice(-100, 2), slice(20, None, -1),
                slice(None, None, 3), slice(None, None, -2),
            ):
                assert view[selection] == tuple(source[selection])
            with pytest.raises(IndexError):
                _ = view[len(source)]
            with pytest.raises(IndexError):
                _ = view[-len(source) - 1]
            with pytest.raises(ValueError):
                _ = view[::0]
            with pytest.raises(TypeError):
                _ = view[1.5]

        # Check point reads are indexed, rather than a scan with LIMIT/OFFSET.
        details = store._con.execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM quotes "
            "WHERE event_id=? AND event_seq=?",
            (11, 17),
        ).fetchall()
        assert any("quote_by_event" in str(item) for item in details)
    finally:
        store.close()
    assert not list((tmp_path / "spool").iterdir())


def test_empty_views_and_pending_batch_flush(tmp_path):
    store = EventQuoteStore(directory=tmp_path / "spool", batch_size=100)
    try:
        empty = store.view(999)
        assert list(empty) == []
        assert empty[:] == ()
        assert empty[::-1] == ()
        assert list(reversed(empty)) == []
        with pytest.raises(IndexError):
            _ = empty[0]

        store.append(1, {"bid": 1.5})
        store.append(2, {"bid": 9.0})
        store.append(1, {"bid": 2.5})
        store.flush()
        assert store.view(1)[:] == ({"bid": 1.5}, {"bid": 2.5})
        assert store.view(2)[-1] == {"bid": 9.0}
    finally:
        store.close()
    assert not list((tmp_path / "spool").iterdir())
