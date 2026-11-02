"""SQLite-backed quote snapshots for the original EMA/VWAP research runners.

The CSV source is still processed in one streaming pass. Event-local indexed\npositions permit fast arbitrary quote access and a single SQL query per slice. The same event/quote
associations and order as the in-memory implementation are preserved; only
the *storage* of per-event captured quotes changes. Use context cleanup after
the research run. This is not an exchange bid/ask history generator.
"""
from __future__ import annotations

import json
import struct
import sqlite3
import tempfile
from pathlib import Path
from collections.abc import Sequence, Iterator

# Exact schema produced by historical quote capture. Seven IEEE-754 doubles
# occupy 56 bytes per captured quote, including non-finite float patterns.
_PACKED_KEYS = (
    "timestamp_ns", "bid", "ask", "bid_size", "ask_size", "volume",
    "open_interest",
)
_PACKED_QUOTE = struct.Struct("<7d")



class EventQuoteView(Sequence):
    def __init__(self, store: "EventQuoteStore", event_id: int):
        self._store = store
        self._event_id = event_id

    def __len__(self) -> int:
        return self._store._counts.get(self._event_id, 0)

    def __iter__(self) -> Iterator[dict[str, float]]:
        cursor = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? ORDER BY event_seq",
            (self._event_id,),
        )
        for row in cursor:
            yield self._store._decode(row[0])

    def __reversed__(self) -> Iterator[dict[str, float]]:
        cursor = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? ORDER BY event_seq DESC",
            (self._event_id,),
        )
        for row in cursor:
            yield self._store._decode(row[0])

    def __getitem__(self, index):
        if isinstance(index, slice):
            positions = range(*index.indices(len(self)))
            if not positions:
                return ()
            low = min(positions[0], positions[-1])
            high = max(positions[0], positions[-1])
            order = "ASC" if positions.step > 0 else "DESC"
            if abs(positions.step) == 1:
                cursor = self._store._con.execute(
                    "SELECT payload FROM quotes "
                    "WHERE event_id=? AND event_seq BETWEEN ? AND ? "
                    f"ORDER BY event_seq {order}",
                    (self._event_id, low, high),
                )
            else:
                cursor = self._store._con.execute(
                    "SELECT payload FROM quotes "
                    "WHERE event_id=? AND event_seq BETWEEN ? AND ? "
                    "AND (event_seq - ?) % ? = 0 "
                    f"ORDER BY event_seq {order}",
                    (self._event_id, low, high, low, abs(positions.step)),
                )
            return tuple(self._store._decode(row[0]) for row in cursor)
        if not isinstance(index, int):
            raise TypeError("Quote indexes must be integers or slices")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        found = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? AND event_seq=?",
            (self._event_id, index),
        ).fetchone()
        if found is None:
            raise IndexError(index)
        return self._store._decode(found[0])


class EventQuoteStore:
    """Temporary on-disk quote spool, with configurable bounded writer batches."""

    def __init__(self, *, directory: Path | None = None,
                 batch_size: int = 4096, max_captured: int | None = None,
                 payload_encoding: str = "JSON"):
        if not 1 <= batch_size <= 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        if max_captured is not None and max_captured < 1:
            raise ValueError("max_captured must be positive")
        if payload_encoding not in {"JSON", "PACKED"}:
            raise ValueError("payload_encoding must be JSON or PACKED")
        self._payload_encoding = payload_encoding
        if directory is not None:
            Path(directory).mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="delta-event-quotes-", dir=directory
        )
        self._con = sqlite3.connect(Path(self._temp.name) / "captured.sqlite3")
        self._con.execute(
            "CREATE TABLE quotes(event_id INTEGER NOT NULL, "
            "event_seq INTEGER NOT NULL, seq INTEGER PRIMARY KEY, payload TEXT)"
        )
        self._con.execute(
            "CREATE UNIQUE INDEX quote_by_event ON quotes(event_id,event_seq)"
        )
        self._counts: dict[int, int] = {}
        self._pending = []
        self._batch_size = batch_size
        self._max_captured = max_captured
        self._total = 0
        self._closed = False

    def view(self, event_id: int) -> EventQuoteView:
        return EventQuoteView(self, event_id)

    def _encode(self, quote: dict[str, float]) -> str | bytes:
        if self._payload_encoding == "JSON":
            return json.dumps(quote, allow_nan=True)
        if set(quote) != set(_PACKED_KEYS):
            raise ValueError("PACKED_QUOTE_SCHEMA_MISMATCH")
        return _PACKED_QUOTE.pack(*(quote[name] for name in _PACKED_KEYS))

    def _decode(self, payload: str | bytes) -> dict[str, float]:
        if self._payload_encoding == "JSON":
            return json.loads(payload)
        return dict(zip(_PACKED_KEYS, _PACKED_QUOTE.unpack(payload)))

    def append(self, event_id: int, quote: dict[str, float]):
        if self._closed:
            raise RuntimeError("Quote spool closed")
        if self._max_captured is not None and self._total >= self._max_captured:
            raise ValueError("CAPTURED_QUOTE_LIMIT_EXCEEDED")
        payload = self._encode(quote)
        event_seq = self._counts.get(event_id, 0)
        self._pending.append((event_id, event_seq, self._total, payload))
        self._counts[event_id] = event_seq + 1
        self._total += 1
        if len(self._pending) >= self._batch_size:
            self.flush()

    def flush(self):
        if self._pending:
            self._con.executemany(
                "INSERT INTO quotes(event_id,event_seq,seq,payload) VALUES(?,?,?,?)",
                self._pending,
            )
            self._con.commit()
            self._pending.clear()

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._con.close()
            finally:
                self._temp.cleanup()

    @property
    def total(self) -> int:
        return self._total
