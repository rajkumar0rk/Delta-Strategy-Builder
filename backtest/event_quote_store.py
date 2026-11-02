"""SQLite-backed quote snapshots for the original EMA/VWAP research runners.

The CSV source is still processed in one streaming pass. The same event/quote
associations and order as the in-memory implementation are preserved; only
the *storage* of per-event captured quotes changes. Use context cleanup after
the research run. This is not an exchange bid/ask history generator.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from collections.abc import Sequence, Iterator


class EventQuoteView(Sequence):
    def __init__(self, store: "EventQuoteStore", event_id: int):
        self._store = store
        self._event_id = event_id

    def __len__(self) -> int:
        return self._store._counts.get(self._event_id, 0)

    def __iter__(self) -> Iterator[dict[str, float]]:
        cursor = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? ORDER BY seq",
            (self._event_id,),
        )
        for row in cursor:
            yield json.loads(row[0])

    def __reversed__(self) -> Iterator[dict[str, float]]:
        cursor = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? ORDER BY seq DESC",
            (self._event_id,),
        )
        for row in cursor:
            yield json.loads(row[0])

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(len(self))))
        if not isinstance(index, int):
            raise TypeError("Quote indexes must be integers or slices")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        found = self._store._con.execute(
            "SELECT payload FROM quotes WHERE event_id=? ORDER BY seq LIMIT 1 OFFSET ?",
            (self._event_id, index),
        ).fetchone()
        if found is None:
            raise IndexError(index)
        return json.loads(found[0])


class EventQuoteStore:
    """Temporary on-disk quote spool, with configurable bounded writer batches."""

    def __init__(self, *, directory: Path | None = None,
                 batch_size: int = 4096, max_captured: int | None = None):
        if not 1 <= batch_size <= 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        if max_captured is not None and max_captured < 1:
            raise ValueError("max_captured must be positive")
        if directory is not None:
            Path(directory).mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="delta-event-quotes-", dir=directory
        )
        self._con = sqlite3.connect(Path(self._temp.name) / "captured.sqlite3")
        self._con.execute(
            "CREATE TABLE quotes(event_id INTEGER, seq INTEGER PRIMARY KEY, payload TEXT)"
        )
        self._con.execute("CREATE INDEX quote_by_event ON quotes(event_id,seq)")
        self._counts: dict[int, int] = {}
        self._pending = []
        self._batch_size = batch_size
        self._max_captured = max_captured
        self._total = 0
        self._closed = False

    def view(self, event_id: int) -> EventQuoteView:
        return EventQuoteView(self, event_id)

    def append(self, event_id: int, quote: dict[str, float]):
        if self._closed:
            raise RuntimeError("Quote spool closed")
        if self._max_captured is not None and self._total >= self._max_captured:
            raise ValueError("CAPTURED_QUOTE_LIMIT_EXCEEDED")
        self._pending.append((event_id, self._total, json.dumps(quote,allow_nan=True)))
        self._counts[event_id] = self._counts.get(event_id, 0) + 1
        self._total += 1
        if len(self._pending) >= self._batch_size:
            self.flush()

    def flush(self):
        if self._pending:
            self._con.executemany(
                "INSERT INTO quotes(event_id,seq,payload) VALUES(?,?,?)",
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
