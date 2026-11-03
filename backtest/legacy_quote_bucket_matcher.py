"""Bounded LRU time-bucket matcher for unordered historical option quotes.

Unlike a monotone SWEEP, this matcher is correct for arbitrary CSV quote
timestamp order and duplicate ticks. It caches *candidate signal windows*
for a fixed time bucket, not the quote values or entire signal catalog.
Every match still applies exact (signal_ns < quote_ns <= end_ns) guards.

Candidate and cache-entry limits are strict upper bounds; dense buckets
fall back to a streaming SQLite cursor without retaining the candidate
list in Python. Original per-quote SQL remains available as the oracle.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from itertools import chain
import sqlite3


NS_MINUTE = 60 * 1_000_000_000


class BoundedQuoteBucketMatcher:
    def __init__(
        self, database: sqlite3.Connection, *,
        bucket_minutes: int = 5,
        max_cache_buckets: int = 256,
        max_cached_candidates: int = 4096,
    ):
        for name, value in (
            ("bucket_minutes", bucket_minutes),
            ("max_cache_buckets", max_cache_buckets),
            ("max_cached_candidates", max_cached_candidates),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.database = database
        self.bucket_ns = bucket_minutes * NS_MINUTE
        self.max_cache_buckets = max_cache_buckets
        self.max_cached_candidates = max_cached_candidates
        self.cache: OrderedDict[
            tuple[str, int], tuple[tuple[int, int, int], ...]
        ] = OrderedDict()
        self.cached_candidates = 0
        self.db_queries = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_evictions = 0
        self.dense_bucket_bypasses = 0
        self.peak_cached_buckets = 0
        self.peak_cached_candidates = 0

    def _evict_oldest(self):
        _key, candidate_rows = self.cache.popitem(last=False)
        self.cached_candidates -= len(candidate_rows)
        self.cache_evictions += 1

    def matching_event_ids(self, symbol: str, current_ns: int) -> Iterator[int]:
        bucket_start = current_ns // self.bucket_ns * self.bucket_ns
        key = (symbol, bucket_start)
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
            candidates = self.cache[key]
            for event_id, start_ns, end_ns in candidates:
                if start_ns < current_ns <= end_ns:
                    yield event_id
            return

        self.cache_misses += 1
        self.db_queries += 1
        cursor = self.database.execute(
            "SELECT event_id,timestamp_ns,end_ns FROM events "
            "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
            "ORDER BY event_id",
            (symbol, bucket_start + self.bucket_ns, bucket_start),
        )
        # Read only up to the configured candidate budget + 1. Very dense
        # buckets are traversed without caching, never materialized fully.
        prefix = cursor.fetchmany(self.max_cached_candidates + 1)
        if len(prefix) > self.max_cached_candidates:
            self.dense_bucket_bypasses += 1
            try:
                for event_id, start_ns, end_ns in chain(prefix, cursor):
                    if start_ns < current_ns <= end_ns:
                        yield event_id
            finally:
                cursor.close()
            return
        cursor.close()

        candidates = tuple(prefix)
        while (
            len(self.cache) >= self.max_cache_buckets
            or self.cached_candidates + len(candidates) > self.max_cached_candidates
        ):
            self._evict_oldest()
        self.cache[key] = candidates
        self.cached_candidates += len(candidates)
        self.peak_cached_buckets = max(self.peak_cached_buckets, len(self.cache))
        self.peak_cached_candidates = max(
            self.peak_cached_candidates, self.cached_candidates
        )
        for event_id, start_ns, end_ns in candidates:
            if start_ns < current_ns <= end_ns:
                yield event_id

    def snapshot_metrics(self) -> dict[str, int | str]:
        return {
            "matching_mode": "BUCKET_CACHE",
            "db_queries": self.db_queries,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_evictions": self.cache_evictions,
            "dense_bucket_bypasses": self.dense_bucket_bypasses,
            "peak_cached_buckets": self.peak_cached_buckets,
            "peak_cached_candidates": self.peak_cached_candidates,
            "max_cache_buckets": self.max_cache_buckets,
            "max_cached_candidates": self.max_cached_candidates,
        }
