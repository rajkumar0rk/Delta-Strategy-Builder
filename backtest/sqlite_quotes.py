"""Disk-backed, ordered, lazy quote sequence for offline legacy research.

SQLite spools selected quotes in bounded batches. Rows are returned as the same
OptionQuoteRow dataclass as the in-memory loader. This is opt-in: legacy callers
that expect tuples keep the original behavior.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from .data import OptionQuoteRow


_SQL = """CREATE TABLE quotes(
    position INTEGER PRIMARY KEY,
    timestamp_ns INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    bid REAL NOT NULL,
    ask REAL NOT NULL,
    bid_size REAL NOT NULL,
    ask_size REAL NOT NULL,
    volume REAL,
    open_interest REAL,
    source_event TEXT NOT NULL
)"""
_SELECT = ("timestamp_ns,symbol,bid,ask,bid_size,ask_size,volume,open_interest,source_event")


class SQLiteQuoteSequence:
    """Sequence-compatible quote spool; call close() for eager cleanup."""

    def __init__(self, rows: Iterable["OptionQuoteRow"], *,
                 batch_size: int = 4096, directory: Path | None = None):
        if batch_size < 1 or batch_size > 100_000:
            raise ValueError("quote_batch_size must be between 1 and 100000")
        if directory is not None:
            Path(directory).mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="delta-legacy-quotes-", dir=directory)
        self._db = Path(self._temp.name) / "quotes.sqlite3"
        self._count = 0
        try:
            with sqlite3.connect(self._db) as con:
                con.execute(_SQL)
                batch = []
                for row in rows:
                    batch.append((
                        self._count, row.timestamp_ns, row.symbol, row.bid,
                        row.ask, row.bid_size, row.ask_size, row.volume,
                        row.open_interest, row.source_event,
                    ))
                    self._count += 1
                    if len(batch) >= batch_size:
                        con.executemany(
                            "INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
                        batch.clear()
                if batch:
                    con.executemany(
                        "INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
        except BaseException:
            self.close()
            raise

    def __len__(self) -> int:
        return self._count

    def __iter__(self) -> Iterator["OptionQuoteRow"]:
        from .data import OptionQuoteRow
        with sqlite3.connect(self._db) as con:
            cursor = con.execute(f"SELECT {_SELECT} FROM quotes ORDER BY position")
            while batch := cursor.fetchmany(2048):
                for fields in batch:
                    yield OptionQuoteRow(*fields)

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(self._count)))
        if not isinstance(index, int):
            raise TypeError("quote index must be an integer or slice")
        if index < 0:
            index += self._count
        if index < 0 or index >= self._count:
            raise IndexError(index)
        from .data import OptionQuoteRow
        with sqlite3.connect(self._db) as con:
            row = con.execute(
                f"SELECT {_SELECT} FROM quotes WHERE position=?", (index,)
            ).fetchone()
        return OptionQuoteRow(*row)

    def close(self) -> None:
        self._temp.cleanup()
