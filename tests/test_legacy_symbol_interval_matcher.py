"""SYMBOL_INDEX must produce identical historical matches with bounded RAM."""
from __future__ import annotations

import csv
import sqlite3

import pytest

from backtest.data import OptionSpec, timestamp_ns
from backtest.ema_vwap_research import SignalEvent
from backtest.legacy_signal_quote_journal import StreamingSignalQuoteJournal
from backtest.legacy_symbol_interval_matcher import BoundedSymbolIntervalMatcher
from backtest.positional_quote_capture import capture_quotes_positional

NS_MINUTE = 60_000_000_000


def _database():
    database = sqlite3.connect(":memory:")
    database.execute(
        "CREATE TABLE events(event_id INTEGER PRIMARY KEY, symbol TEXT, "
        "timestamp_ns INTEGER, end_ns INTEGER)"
    )
    database.executemany(
        "INSERT INTO events VALUES(?,?,?,?)",
        [
            (1, "BTC-CE", 0, 5*NS_MINUTE),
            (2, "ETH-CE", 0, 5*NS_MINUTE),
            (3, "BTC-CE", 1*NS_MINUTE, 8*NS_MINUTE),
            (4, "ETH-CE", 4*NS_MINUTE, 8*NS_MINUTE),
            (5, "BTC-CE", 2*NS_MINUTE, 4*NS_MINUTE),
            (6, "SOL-CE", 0, 20*NS_MINUTE),
            (7, "BTC-CE", 5*NS_MINUTE, 10*NS_MINUTE),
            (8, "BTC-CE", 8*NS_MINUTE, 11*NS_MINUTE),
            (9, "BTC-CE", 8*NS_MINUTE, 11*NS_MINUTE),
        ],
    )
    return database


@pytest.mark.parametrize("max_symbols,max_candidates", [
    (1, 1), (1, 3), (2, 5), (3, 30), (16, 40),
])
def test_symbol_matches_original_sql_with_unordered_and_duplicate_ticks(
    max_symbols, max_candidates,
):
    database = _database()
    matcher = BoundedSymbolIntervalMatcher(
        database, max_cached_symbols=max_symbols,
        max_cached_candidates=max_candidates,
    )
    sequence = [
        ("BTC-CE", 6), ("ETH-CE", 4), ("BTC-CE", 4),
        ("SOL-CE", 20), ("BTC-CE", 5), ("BTC-CE", 0),
        ("BTC-CE", 11), ("UNKNOWN-CE", 8),
        ("ETH-CE", 8), ("ETH-CE", 1), ("BTC-CE", 8),
        ("BTC-CE", 6), ("SOL-CE", 20), ("ETH-CE", 4),
        ("BTC-CE", 2), ("BTC-CE", 10),
    ] * 7
    for symbol, minute in sequence:
        ns = minute * NS_MINUTE
        expected = [
            result[0] for result in database.execute(
                "SELECT event_id FROM events "
                "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
                "ORDER BY event_id",
                (symbol, ns, ns),
            )
        ]
        assert list(matcher.matching_event_ids(symbol, ns)) == expected
        metrics = matcher.snapshot_metrics()
        assert metrics["peak_cached_symbols"] <= max_symbols
        assert metrics["peak_cached_candidates"] <= max_candidates
        assert metrics["peak_dense_symbols"] <= max_symbols
    assert matcher.snapshot_metrics()["matching_mode"] == "SYMBOL_INDEX"
    database.close()


def test_repeated_ticks_reuse_symbol_intervals_without_db_queries():
    database = _database()
    matcher = BoundedSymbolIntervalMatcher(
        database, max_cached_symbols=8, max_cached_candidates=40,
    )
    for i in range(100):
        ns = (2 + i % 8) * NS_MINUTE
        list(matcher.matching_event_ids("BTC-CE", ns))
        list(matcher.matching_event_ids("ETH-CE", ns))
        list(matcher.matching_event_ids("SOL-CE", ns))
    metrics = matcher.snapshot_metrics()
    assert metrics["db_queries"] == 3
    assert metrics["cache_misses"] == 3
    assert metrics["cache_hits"] == 297
    assert metrics["cache_evictions"] == 0
    assert metrics["peak_cached_candidates"] == 9
    database.close()


def test_dense_symbol_uses_original_sql_without_unbounded_candidate_cache():
    database = _database()
    matcher = BoundedSymbolIntervalMatcher(
        database, max_cached_symbols=2, max_cached_candidates=1,
    )
    for i in range(25):
        ns = (i % 10 + 1) * NS_MINUTE
        expected = [
            e[0] for e in database.execute(
                "SELECT event_id FROM events "
                "WHERE symbol=? AND timestamp_ns < ? AND end_ns >= ? "
                "ORDER BY event_id", ("BTC-CE", ns, ns),
            )
        ]
        assert list(matcher.matching_event_ids("BTC-CE", ns)) == expected
    metrics = matcher.snapshot_metrics()
    assert metrics["dense_symbol_bypasses"] == 25
    assert metrics["cache_misses"] == 1
    assert metrics["peak_cached_candidates"] == 0
    assert metrics["peak_dense_symbols"] == 1
    database.close()


def _spec(symbol):
    return OptionSpec(
        symbol=symbol, source_symbol=symbol,
        expiry="2026-09-04", strike=100000.0,
        option_type="CE", activation_ns=timestamp_ns("2026-09-01T00:00:00Z"),
        expiration_ns=timestamp_ns("2026-09-04T00:00:00Z"),
        price_precision=2, size_precision=0, price_increment=0.01,
        size_increment=1.0, lot_size=1.0, min_quantity=1.0,
        contract_value=0.001,
    )


def _event(spec, minute):
    return SignalEvent(
        timestamp_ns=timestamp_ns(f"2026-09-01T00:{minute:02d}:00Z"),
        direction="CALL", underlying=100000.0,
        option=spec, quotes=[], ema_regime_start_ns=123,
    )


def _quotes(path):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "timestamp", "symbol", "bid", "ask", "bid_size",
            "ask_size", "volume", "open_interest",
        ])
        writer.writeheader()
        for minute, symbol in [
            (4, "BTC-CE"), (2, "ETH-CE"), (6, "BTC-CE"),
            (1, "BTC-CE"), (4, "BTC-CE"), (7, "ETH-CE"),
            (9, "BTC-CE"), (8, "BTC-CE"), (5, "ETH-CE"),
        ]:
            writer.writerow({
                "timestamp": f"2026-09-01T00:{minute:02d}:00Z",
                "symbol": symbol, "bid": 1 + minute,
                "ask": 1.25 + minute, "bid_size": 3,
                "ask_size": 4, "volume": 50, "open_interest": 100,
            })


@pytest.mark.parametrize("max_symbols,max_candidates", [
    (1, 1), (2, 4), (256, 4096),
])
def test_full_journal_quote_replay_matches_legacy_positional_capture(
    tmp_path, max_symbols, max_candidates,
):
    btc, eth = _spec("BTC-CE"), _spec("ETH-CE")
    original_a = [_event(btc, 0), _event(eth, 2), _event(btc, 5)]
    original_b = [_event(btc, 0), _event(eth, 4)]
    path = tmp_path / "quotes.csv"
    _quotes(path)
    capture_quotes_positional(
        path, original_a + original_b, horizon_minutes=5,
    )
    with StreamingSignalQuoteJournal([btc, eth]) as journal:
        journal.add_signals("A", original_a, horizon_minutes=5)
        journal.add_signals("B", original_b, horizon_minutes=5)
        journal.capture_quotes(
            path, matching_mode="SYMBOL_INDEX",
            max_cached_symbols=max_symbols,
            max_cached_candidates=max_candidates,
        )
        for originals, config in ((original_a, "A"), (original_b, "B")):
            streamed = list(journal.iter_events(config))
            assert len(originals) == len(streamed)
            for left, right in zip(originals, streamed):
                assert left.option == right.option
                assert left.timestamp_ns == right.timestamp_ns
                assert list(left.quotes) == list(right.quotes)
                assert list(reversed(left.quotes)) == list(reversed(right.quotes))
        metrics = journal.snapshot_metrics()
        assert metrics["matching_mode"] == "SYMBOL_INDEX"
        assert metrics["peak_cached_symbols"] <= max_symbols
        assert metrics["peak_cached_candidates"] <= max_candidates
        assert metrics["captured_quote_rows"] == sum(
            len(event.quotes) for event in original_a + original_b
        )


@pytest.mark.parametrize("invalid", [
    {"max_cached_symbols": 0}, {"max_cached_symbols": True},
    {"max_cached_candidates": 0}, {"max_cached_candidates": -1},
    {"matching_mode": "BAD"},
])
def test_invalid_symbol_index_configuration_does_not_start_capture(
    tmp_path, invalid,
):
    option = _spec("BTC-CE")
    with StreamingSignalQuoteJournal([option]) as journal:
        with pytest.raises(ValueError):
            arguments = {"matching_mode": "SYMBOL_INDEX", **invalid}
            journal.capture_quotes(
                tmp_path / "nonexistent.csv", **arguments,
            )
        journal.add_signal("A", _event(option, 0))


def test_partial_capture_failure_cannot_be_replayed_or_retried(tmp_path):
    option = _spec("BTC-CE")
    path = tmp_path / "quotes.csv"
    _quotes(path)
    with StreamingSignalQuoteJournal(
        [option], max_captured_quotes=1,
    ) as journal:
        journal.add_signal("A", _event(option, 0), horizon_minutes=10)
        with pytest.raises(ValueError, match="CAPTURED_QUOTE_LIMIT"):
            journal.capture_quotes(
                path, matching_mode="SYMBOL_INDEX",
            )
        with pytest.raises(RuntimeError, match="NOT_CAPTURED"):
            list(journal.iter_events("A"))
        with pytest.raises(RuntimeError, match="ALREADY_CAPTURED"):
            journal.capture_quotes(
                path, matching_mode="SYMBOL_INDEX",
            )
