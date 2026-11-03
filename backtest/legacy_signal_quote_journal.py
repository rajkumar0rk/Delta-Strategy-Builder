"""Experimental disk-backed bridge from streamed H6 signals to quote replay.

Signals are added incrementally and stored by stable SQLite IDs instead of
being retained as SignalEvent lists. Capture scans the original normalized
quote CSV once and appends the exact matching quote payloads to the existing
EventQuoteStore under those stable IDs. Replay yields SignalEvent objects with
the same Sequence quote semantics expected by simulate_trade().

This module is an isolated research building block. It does NOT replace
run_dataset, compute option true ranges, execute any trades, or guarantee
end-to-end bounded RSS. Its signal and quote results must pass historical
parity before integration with the legacy simulation pipeline.
"""
from __future__ import annotations

import math
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator, Iterable

from .data import OptionSpec, timestamp_ns
from .ema_vwap_research import SignalEvent
from .event_quote_store import EventQuoteStore
from .positional_quote_capture import _payload, _quote_rows, _required

NS_MINUTE = 60 * 1_000_000_000


class StreamingSignalQuoteJournal:
    """Spool signal metadata and captured quotes with stable replay identities."""

    def __init__(
        self,
        specs: Iterable[OptionSpec],
        *,
        directory: Path | None = None,
        quote_batch_size: int = 4096,
        max_signals: int | None = None,
        max_captured_quotes: int | None = None,
    ):
        if max_signals is not None and (
            type(max_signals) is not int or max_signals < 1
        ):
            raise ValueError("max_signals must be a positive integer")
        if directory is not None:
            Path(directory).mkdir(parents=True, exist_ok=True)
        self._specs: dict[str, OptionSpec] = {}
        for option in specs:
            if option.symbol in self._specs:
                raise ValueError("DUPLICATE_OPTION_SYMBOL")
            self._specs[option.symbol] = option
        self._temp = tempfile.TemporaryDirectory(
            prefix="delta-signal-quote-journal-", dir=directory,
        )
        try:
            self._database = sqlite3.connect(
                Path(self._temp.name) / "signals.sqlite3"
            )
            self._database.execute(
                "CREATE TABLE events ("
                "event_id INTEGER PRIMARY KEY, config TEXT NOT NULL, "
                "ordinal INTEGER NOT NULL, timestamp_ns INTEGER NOT NULL, "
                "end_ns INTEGER NOT NULL, symbol TEXT NOT NULL, "
                "direction TEXT NOT NULL, underlying REAL NOT NULL, "
                "regime_start_ns INTEGER NOT NULL, entry_type TEXT NOT NULL)"
            )
            self._database.execute(
                "CREATE INDEX events_by_symbol ON events(symbol, timestamp_ns, end_ns)"
            )
            self._database.execute(
                "CREATE UNIQUE INDEX events_by_config ON events(config, ordinal)"
            )
            self._quotes = EventQuoteStore(
                directory=Path(self._temp.name),
                batch_size=quote_batch_size,
                max_captured=max_captured_quotes,
                payload_encoding="PACKED",
            )
        except BaseException:
            if hasattr(self, "_database"):
                self._database.close()
            self._temp.cleanup()
            raise
        self._last_timestamps: dict[str, int] = {}
        self._config_counts: dict[str, int] = {}
        self._symbols: set[str] = set()
        self._max_signals = max_signals
        self._total_signals = 0
        self._captured = False
        self._capture_started = False
        self._closed = False
        self._matching_metrics: dict[str, int | str] = {
            "matching_mode": "SQL", "db_queries": 0,
            "eligible_quote_rows": 0,
        }

    def __enter__(self) -> "StreamingSignalQuoteJournal":
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.close()

    def add_signal(
        self, config: str, event: SignalEvent, *,
        horizon_minutes: float | None = 65,
    ) -> None:
        if self._closed:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_CLOSED")
        if self._capture_started:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_ALREADY_CAPTURED")
        if not isinstance(config, str) or not config:
            raise ValueError("config must be nonempty")
        if self._max_signals is not None and self._total_signals >= self._max_signals:
            raise ValueError("LEGACY_SIGNAL_EVENT_LIMIT_EXCEEDED")
        if event.option.symbol not in self._specs:
            raise ValueError("SIGNAL_OPTION_NOT_IN_INSTRUMENT_CATALOG")
        if event.option != self._specs[event.option.symbol]:
            raise ValueError("SIGNAL_OPTION_CATALOG_MISMATCH")
        if horizon_minutes is not None and (
            not math.isfinite(horizon_minutes) or horizon_minutes < 0
        ):
            raise ValueError("horizon_minutes must be nonnegative and finite")
        last = self._last_timestamps.get(config)
        if last is not None and event.timestamp_ns < last:
            raise ValueError("SIGNAL_TIMESTAMP_OUT_OF_ORDER")
        # Match original capture end (inclusive), strict timestamp > signal.
        limit = (
            event.option.expiration_ns
            if horizon_minutes is None
            else min(
                event.option.expiration_ns,
                event.timestamp_ns + int(horizon_minutes * NS_MINUTE),
            )
        )
        ordinal = self._config_counts.get(config, 0)
        self._database.execute(
            "INSERT INTO events("
            "config,ordinal,timestamp_ns,end_ns,symbol,direction,"
            "underlying,regime_start_ns,entry_type) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                config, ordinal, event.timestamp_ns, limit,
                event.option.symbol, event.direction, event.underlying,
                event.ema_regime_start_ns, event.entry_type,
            ),
        )
        self._config_counts[config] = ordinal + 1
        self._last_timestamps[config] = event.timestamp_ns
        self._symbols.add(event.option.symbol)
        self._total_signals += 1

    def add_signals(
        self, config: str, events: Iterable[SignalEvent], *,
        horizon_minutes: float | None = 65,
    ) -> None:
        for event in events:
            self.add_signal(config, event, horizon_minutes=horizon_minutes)

    def capture_quotes(
        self, path: Path, *,
        matching_mode: str = "SQL",
        bucket_minutes: int = 5,
        max_cache_buckets: int = 256,
        max_cached_candidates: int = 4096,
    ) -> None:
        """Capture event-local quote rows in source CSV order, including duplicates.

        Like LEGACY positional capture, this does not require globally sorted
        quote CSV timestamps. If the same symbol is seen out of order, both
        implementations retain that original arrival order.
        """
        if self._closed:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_CLOSED")
        if self._capture_started:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_ALREADY_CAPTURED")
        if matching_mode not in {"SQL", "BUCKET_CACHE"}:
            raise ValueError("matching_mode must be SQL or BUCKET_CACHE")
        from .legacy_quote_bucket_matcher import BoundedQuoteBucketMatcher
        matcher = (
            BoundedQuoteBucketMatcher(
                self._database,
                bucket_minutes=bucket_minutes,
                max_cache_buckets=max_cache_buckets,
                max_cached_candidates=max_cached_candidates,
            )
            if matching_mode == "BUCKET_CACHE" else None
        )
        # A partial failed capture cannot safely be replayed or retried.
        self._capture_started = True
        self._database.commit()
        eligible_rows = 0
        sql_queries = 0
        try:
            for symbol, row, columns in _quote_rows(path):
                if symbol not in self._symbols:
                    continue
                current_ns = timestamp_ns(_required(row, columns, "timestamp"))
                eligible_rows += 1
                if matcher is None:
                    # Preserve the original independent SQL oracle.
                    matching_ids = (
                        result[0] for result in self._database.execute(
                            "SELECT event_id FROM events "
                            "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
                            "ORDER BY event_id",
                            (symbol, current_ns, current_ns),
                        )
                    )
                    sql_queries += 1
                else:
                    matching_ids = matcher.matching_event_ids(symbol, current_ns)
                # Decode only if a signal consumes this quote; input arrival
                # order and duplicate quote rows are never changed.
                quote = None
                for event_id in matching_ids:
                    if quote is None:
                        quote = _payload(row, columns, current_ns)
                    self._quotes.append(event_id, quote)
            self._quotes.flush()
            self._captured = True
        finally:
            self._matching_metrics = (
                matcher.snapshot_metrics()
                if matcher is not None
                else {"matching_mode": "SQL", "db_queries": sql_queries}
            )
            self._matching_metrics["eligible_quote_rows"] = eligible_rows

    def count(self, config: str) -> int:
        return self._config_counts.get(config, 0)

    def iter_events(self, config: str) -> Iterator[SignalEvent]:
        """Replay complete event quote sequences while this journal is open."""
        if self._closed:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_CLOSED")
        if not self._captured:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_NOT_CAPTURED")
        for (
            event_id, ns, symbol, direction, underlying, regime, entry_type,
        ) in self._database.execute(
            "SELECT event_id,timestamp_ns,symbol,direction,underlying,"
            "regime_start_ns,entry_type FROM events WHERE config=? "
            "ORDER BY ordinal",
            (config,),
        ):
            yield SignalEvent(
                timestamp_ns=ns, direction=direction,
                underlying=underlying, option=self._specs[symbol],
                quotes=self._quotes.view(event_id),
                ema_regime_start_ns=regime, entry_type=entry_type,
            )

    def snapshot_metrics(self) -> dict[str, int | str]:
        if self._closed:
            raise RuntimeError("SIGNAL_QUOTE_JOURNAL_CLOSED")
        quote_metrics = self._quotes.snapshot_metrics()
        return {
            "signals": self._total_signals,
            "configs": len(self._config_counts),
            "selected_symbols": len(self._symbols),
            **quote_metrics,
            **self._matching_metrics,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._quotes.close()
        finally:
            try:
                self._database.close()
            finally:
                self._temp.cleanup()
