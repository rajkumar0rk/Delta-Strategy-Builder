"""Bounded per-symbol interval index for arbitrary-order H6 quote CSV capture.

Quoted symbols repeat across many historical ticks. A time-bucket cache
repeatedly evicts candidate windows as historical symbols interleave.
This opt-in matcher instead holds a bounded LRU of each selected symbol's
*signal intervals* (event_id, signal_ns, end_ns), never the quote rows.

Matching is exact: signal_ns < quote_ns <= end_ns, and event IDs are
returned in original ascending order. No timestamp-order assumption.
Dense symbols exceed the configured candidate cap and use the original
streaming SQLite interval query; no unbounded materialization.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
import sqlite3


class BoundedSymbolIntervalMatcher:
    def __init__(
        self, database: sqlite3.Connection, *,
        max_cached_symbols: int = 256,
        max_cached_candidates: int = 4096,
    ):
        for name, value in (
            ("max_cached_symbols", max_cached_symbols),
            ("max_cached_candidates", max_cached_candidates),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.database = database
        self.max_cached_symbols = max_cached_symbols
        self.max_cached_candidates = max_cached_candidates
        self.cache: OrderedDict[str, tuple[tuple[int, int, int], ...]] = OrderedDict()
        # Dense symbols must not re-load max_cached_candidates + 1 interval
        # rows for every quote. Their negative-cache entries are LRU-bounded.
        self.dense: OrderedDict[str, None] = OrderedDict()
        self.cached_candidates = 0
        self.db_queries = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_evictions = 0
        self.dense_symbol_bypasses = 0
        self.peak_cached_symbols = 0
        self.peak_cached_candidates = 0
        self.peak_dense_symbols = 0

    def _evict_oldest(self) -> None:
        _symbol, rows = self.cache.popitem(last=False)
        self.cached_candidates -= len(rows)
        self.cache_evictions += 1

    def _query_matches(self, symbol: str, timestamp_ns: int) -> Iterator[int]:
        self.db_queries += 1
        cursor = self.database.execute(
            "SELECT event_id FROM events "
            "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
            "ORDER BY event_id",
            (symbol, timestamp_ns, timestamp_ns),
        )
        try:
            for (event_id,) in cursor:
                yield event_id
        finally:
            cursor.close()

    def _remember_dense(self, symbol: str) -> None:
        self.dense[symbol] = None
        self.dense.move_to_end(symbol)
        if len(self.dense) > self.max_cached_symbols:
            self.dense.popitem(last=False)
        self.peak_dense_symbols = max(self.peak_dense_symbols, len(self.dense))

    def matching_event_ids(self, symbol: str, timestamp_ns: int) -> Iterator[int]:
        if symbol in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(symbol)
            intervals = self.cache[symbol]
        elif symbol in self.dense:
            self.dense.move_to_end(symbol)
            self.dense_symbol_bypasses += 1
            yield from self._query_matches(symbol, timestamp_ns)
            return
        else:
            self.cache_misses += 1
            self.db_queries += 1
            cursor = self.database.execute(
                "SELECT event_id,timestamp_ns,end_ns "
                "FROM events WHERE symbol=? ORDER BY event_id",
                (symbol,),
            )
            try:
                # Explicitly cap the candidate materialization before we
                # can tell whether a symbol is cacheable.
                prefix = cursor.fetchmany(self.max_cached_candidates + 1)
            finally:
                cursor.close()
            if len(prefix) > self.max_cached_candidates:
                self._remember_dense(symbol)
                self.dense_symbol_bypasses += 1
                yield from self._query_matches(symbol, timestamp_ns)
                return
            intervals = tuple(prefix)
            while (
                len(self.cache) >= self.max_cached_symbols
                or self.cached_candidates + len(intervals)
                > self.max_cached_candidates
            ):
                self._evict_oldest()
            self.cache[symbol] = intervals
            self.cached_candidates += len(intervals)
            self.peak_cached_symbols = max(
                self.peak_cached_symbols, len(self.cache),
            )
            self.peak_cached_candidates = max(
                self.peak_cached_candidates, self.cached_candidates,
            )
        for event_id, start_ns, end_ns in intervals:
            if start_ns < timestamp_ns <= end_ns:
                yield event_id

    def snapshot_metrics(self) -> dict[str, int | str]:
        return {
            "matching_mode": "SYMBOL_INDEX",
            "db_queries": self.db_queries,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_evictions": self.cache_evictions,
            "dense_symbol_bypasses": self.dense_symbol_bypasses,
            "peak_cached_symbols": self.peak_cached_symbols,
            "peak_cached_candidates": self.peak_cached_candidates,
            "peak_dense_symbols": self.peak_dense_symbols,
            "max_cached_symbols": self.max_cached_symbols,
            "max_cached_candidates": self.max_cached_candidates,
        }
