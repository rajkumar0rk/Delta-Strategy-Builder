"""Bounded bucket matcher must preserve the original SQLite interval query."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from backtest.data import OptionSpec, timestamp_ns
from backtest.ema_vwap_research import SignalEvent
from backtest.legacy_quote_bucket_matcher import (
    BoundedQuoteBucketMatcher, NS_MINUTE,
)
from backtest.legacy_signal_quote_journal import StreamingSignalQuoteJournal
from backtest.positional_quote_capture import capture_quotes_positional


def _database():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE events(event_id INTEGER PRIMARY KEY, symbol TEXT, "
        "timestamp_ns INTEGER, end_ns INTEGER)"
    )
    db.executemany(
        "INSERT INTO events VALUES(?,?,?,?)",
        [
            (1, "BTC-CE", 0, 5 * NS_MINUTE),
            (2, "BTC-CE", 1 * NS_MINUTE, 8 * NS_MINUTE),
            (3, "BTC-CE", 2 * NS_MINUTE, 4 * NS_MINUTE),
            (4, "BTC-CE", 5 * NS_MINUTE, 10 * NS_MINUTE),
            (5, "ETH-CE", 0, 5 * NS_MINUTE),
            (6, "BTC-CE", 8 * NS_MINUTE, 11 * NS_MINUTE),
        ],
    )
    return db


@pytest.mark.parametrize("bucket_minutes,cache_buckets,candidate_cap", [
    (1, 1, 1),
    (5, 1, 2),
    (5, 2, 4),
    (10, 4, 20),
])
def test_bucket_matcher_exactly_matches_per_quote_sql_in_arbitrary_order(
    bucket_minutes, cache_buckets, candidate_cap,
):
    db = _database()
    matcher = BoundedQuoteBucketMatcher(
        db, bucket_minutes=bucket_minutes,
        max_cache_buckets=cache_buckets,
        max_cached_candidates=candidate_cap,
    )
    inputs = [
        ("BTC-CE", 6 * NS_MINUTE),
        ("BTC-CE", 2 * NS_MINUTE),
        ("BTC-CE", 2 * NS_MINUTE),  # duplicates
        ("BTC-CE", 5 * NS_MINUTE),
        ("BTC-CE", 0),
        ("BTC-CE", 8 * NS_MINUTE),
        ("ETH-CE", 4 * NS_MINUTE),
        ("BTC-CE", 11 * NS_MINUTE),
        ("BTC-CE", 3 * NS_MINUTE),
        ("BTC-CE", 1 * NS_MINUTE),
        ("ETH-CE", 5 * NS_MINUTE),
        ("BTC-CE", 10 * NS_MINUTE + 1),
        ("BTC-CE", 12 * NS_MINUTE),
        ("ETH-CE", 2 * NS_MINUTE),
        ("BTC-CE", 6 * NS_MINUTE),
    ] * 5
    for symbol, now in inputs:
        expected = [
            row[0] for row in db.execute(
                "SELECT event_id FROM events "
                "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
                "ORDER BY event_id",
                (symbol, now, now),
            )
        ]
        assert list(matcher.matching_event_ids(symbol, now)) == expected
        metrics = matcher.snapshot_metrics()
        assert metrics["peak_cached_buckets"] <= cache_buckets
        assert metrics["peak_cached_candidates"] <= candidate_cap
    assert matcher.snapshot_metrics()["db_queries"] <= len(inputs)
    db.close()


def _spec():
    return OptionSpec(
        symbol="BTC-CE", source_symbol="BTC-CE",
        expiry="2026-09-04", strike=100000.0, option_type="CE",
        activation_ns=timestamp_ns("2026-09-01T00:00:00Z"),
        expiration_ns=timestamp_ns("2026-09-04T00:00:00Z"),
        price_precision=2, size_precision=0, price_increment=.01,
        size_increment=1.0, lot_size=1.0,
        min_quantity=1.0, contract_value=.001,
    )


def _event(spec, minute):
    return SignalEvent(
        timestamp_ns=timestamp_ns(f"2026-09-01T00:{minute:02d}:00Z"),
        direction="CALL", underlying=100000.0,
        option=spec, quotes=[], ema_regime_start_ns=0,
    )


def _write_quotes(path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "symbol", "timestamp", "bid", "ask",
            "bid_size", "ask_size", "volume", "open_interest",
        ])
        writer.writeheader()
        # Mix time buckets and allow repeated records and unsorted times.
        seconds = (
            [240, 120, 300, 420, 0, 60, 240, 600, 301]
            + list(range(120, 235, 5))
        )
        for index, second in enumerate(seconds):
            minute, part = divmod(second, 60)
            writer.writerow({
                "symbol": "BTC-CE",
                "timestamp": f"2026-09-01T00:{minute:02d}:{part:02d}Z",
                "bid": 2.0 + index / 100,
                "ask": 2.2 + index / 100,
                "bid_size": 2, "ask_size": 5,
                "volume": 10, "open_interest": 50,
            })


@pytest.mark.parametrize("buckets,candidate_cap", [(1, 1), (2, 2), (4, 10)])
def test_quote_journal_cached_mode_preserves_quote_order_and_contracts(
    tmp_path, buckets, candidate_cap,
):
    spec = _spec()
    path = tmp_path / "quotes.csv"
    _write_quotes(path)
    a = [_event(spec, 0), _event(spec, 2), _event(spec, 5)]
    b = [_event(spec, 0), _event(spec, 1)]
    capture_quotes_positional(path, a + b, horizon_minutes=5)
    scratch = tmp_path / "scratch"
    with StreamingSignalQuoteJournal([spec], directory=scratch) as journal:
        journal.add_signals("A", a, horizon_minutes=5)
        journal.add_signals("B", b, horizon_minutes=5)
        journal.capture_quotes(
            path, matching_mode="BUCKET_CACHE",
            bucket_minutes=5, max_cache_buckets=buckets,
            max_cached_candidates=candidate_cap,
        )
        for original, replay in zip(a, journal.iter_events("A")):
            assert list(original.quotes) == list(replay.quotes)
        for original, replay in zip(b, journal.iter_events("B")):
            assert list(original.quotes) == list(replay.quotes)
        metrics = journal.snapshot_metrics()
        assert metrics["matching_mode"] == "BUCKET_CACHE"
        assert metrics["captured_quote_rows"] == sum(
            len(e.quotes) for e in a+b
        )
        assert metrics["peak_cached_buckets"] <= buckets
        assert metrics["peak_cached_candidates"] <= candidate_cap
    assert not list(scratch.iterdir())


def test_cached_quote_matcher_reduces_queries_for_repeated_time_buckets(
    tmp_path,
):
    spec = _spec()
    path = tmp_path / "quotes.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "symbol", "timestamp", "bid", "ask"
        ])
        writer.writeheader()
        for second in range(10, 290):
            minute, remainder = divmod(second, 60)
            writer.writerow({
                "symbol": spec.symbol,
                "timestamp": f"2026-09-01T00:{minute:02d}:{remainder:02d}Z",
                "bid": 1, "ask": 1.2,
            })
    source = [_event(spec, 0)]
    capture_quotes_positional(path, source, horizon_minutes=5)
    with StreamingSignalQuoteJournal([spec]) as journal:
        journal.add_signal("A", _event(spec, 0), horizon_minutes=5)
        journal.capture_quotes(
            path, matching_mode="BUCKET_CACHE",
            bucket_minutes=5,
        )
        metrics = journal.snapshot_metrics()
        assert metrics["eligible_quote_rows"] == 280
        assert metrics["db_queries"] == 1
        assert metrics["cache_hits"] == 279
        assert len(next(journal.iter_events("A")).quotes) == 280
        assert list(next(journal.iter_events("A")).quotes) == source[0].quotes


@pytest.mark.parametrize("arg", [
    {"matching_mode": "INVALID"},
    {"matching_mode": "BUCKET_CACHE", "bucket_minutes": 0},
    {"matching_mode": "BUCKET_CACHE", "max_cache_buckets": False},
    {"matching_mode": "BUCKET_CACHE", "max_cached_candidates": -1},
])
def test_bad_matching_mode_or_cache_settings_do_not_start_capture(tmp_path, arg):
    with StreamingSignalQuoteJournal([_spec()]) as journal:
        with pytest.raises(ValueError):
            journal.capture_quotes(tmp_path / "missing.csv", **arg)
        assert journal.count("A") == 0
        journal.add_signal("A", _event(_spec(), 0))


def test_cached_capture_fails_closed_after_quote_limit(tmp_path):
    spec = _spec()
    path = tmp_path / "quotes.csv"
    _write_quotes(path)
    with StreamingSignalQuoteJournal(
        [spec], max_captured_quotes=1,
    ) as journal:
        journal.add_signal("A", _event(spec, 0), horizon_minutes=5)
        with pytest.raises(ValueError, match="CAPTURED_QUOTE_LIMIT"):
            journal.capture_quotes(path, matching_mode="BUCKET_CACHE")
        with pytest.raises(RuntimeError, match="NOT_CAPTURED"):
            list(journal.iter_events("A"))
        with pytest.raises(RuntimeError, match="ALREADY_CAPTURED"):
            journal.capture_quotes(path, matching_mode="BUCKET_CACHE")
