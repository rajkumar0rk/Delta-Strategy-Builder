"""Parity and fail-closed tests for the streaming signal/quote journal."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backtest.data import OptionSpec, timestamp_ns
from backtest.ema_vwap_research import SignalEvent
from backtest.legacy_signal_quote_journal import StreamingSignalQuoteJournal
from backtest.positional_quote_capture import capture_quotes_positional


def _spec(symbol: str) -> OptionSpec:
    return OptionSpec(
        symbol=symbol, source_symbol=symbol, expiry="2026-09-04",
        strike=100000.0, option_type="CE",
        activation_ns=timestamp_ns("2026-09-01T00:00:00Z"),
        expiration_ns=timestamp_ns("2026-09-04T00:00:00Z"),
        price_precision=2, size_precision=0, price_increment=0.01,
        size_increment=1.0, lot_size=1.0, min_quantity=1.0,
        contract_value=0.001,
    )


def _event(spec, minute, direction="CALL"):
    return SignalEvent(
        timestamp_ns=timestamp_ns(f"2026-09-01T00:{minute:02d}:00Z"),
        direction=direction, underlying=100000.0 + minute,
        option=spec, quotes=[], ema_regime_start_ns=1234,
        entry_type="BASELINE",
    )


def _csv(path: Path):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "timestamp", "symbol", "bid", "ask",
            "bid_size", "ask_size", "volume", "open_interest",
        ])
        writer.writeheader()
        # Deliberately out-of-order source rows (legacy capture allows this),
        # symbols never used, duplicated ticks, and different option symbols.
        for minute, symbol in (
            (6, "BTC-CE"), (4, "BTC-CE"), (4, "BTC-CE"),
            (8, "BTC-CE"), (3, "OTHER-CE"), (5, "OTHER-CE"),
            (8, "OTHER-CE"), (10, "BTC-CE"),
        ):
            writer.writerow({
                "timestamp": f"2026-09-01T00:{minute:02d}:00Z",
                "symbol": symbol, "bid": 1.1 + minute,
                "ask": 1.3 + minute, "bid_size": 7.0,
                "ask_size": 8.0, "volume": 31.0,
                "open_interest": 22.0,
            })


def _compare_fields(original, replayed):
    assert original.timestamp_ns == replayed.timestamp_ns
    assert original.option == replayed.option
    assert original.direction == replayed.direction
    assert original.underlying == replayed.underlying
    assert original.ema_regime_start_ns == replayed.ema_regime_start_ns
    assert original.entry_type == replayed.entry_type
    assert list(original.quotes) == list(replayed.quotes)
    assert list(reversed(original.quotes)) == list(reversed(replayed.quotes))
    assert len(original.quotes) == len(replayed.quotes)
    if original.quotes:
        assert original.quotes[0] == replayed.quotes[0]
        assert original.quotes[-1] == replayed.quotes[-1]
        assert original.quotes[::2] == list(replayed.quotes[::2])


def test_streamed_journal_replays_legacy_quote_capture_exactly(tmp_path):
    first, second = _spec("BTC-CE"), _spec("OTHER-CE")
    original_a = [_event(first, 2), _event(second, 3), _event(first, 5)]
    original_b = [_event(first, 2), _event(second, 4)]
    file = tmp_path / "quotes.csv"
    _csv(file)
    capture_quotes_positional(
        file, original_a + original_b, horizon_minutes=5,
    )
    scratch = tmp_path / "scratch"
    with StreamingSignalQuoteJournal(
        [first, second], directory=scratch, quote_batch_size=2,
    ) as journal:
        journal.add_signals("A", original_a, horizon_minutes=5)
        journal.add_signals("B", original_b, horizon_minutes=5)
        assert journal.count("A") == 3
        assert journal.count("B") == 2
        with pytest.raises(RuntimeError, match="NOT_CAPTURED"):
            list(journal.iter_events("A"))
        journal.capture_quotes(file)
        assert journal.snapshot_metrics()["signals"] == 5
        assert journal.snapshot_metrics()["captured_quote_rows"] == sum(
            len(x.quotes) for x in original_a + original_b
        )
        for left, right in zip(original_a, journal.iter_events("A")):
            _compare_fields(left, right)
        for left, right in zip(original_b, journal.iter_events("B")):
            _compare_fields(left, right)
        assert list(journal.iter_events("UNKNOWN")) == []
        with pytest.raises(RuntimeError, match="ALREADY_CAPTURED"):
            journal.add_signal("A", _event(first, 12))
        with pytest.raises(RuntimeError, match="ALREADY_CAPTURED"):
            journal.capture_quotes(file)
    assert not list(scratch.iterdir())


def test_journal_fail_closed_signal_and_quote_limits(tmp_path):
    one = _spec("BTC-CE")
    path = tmp_path / "quotes.csv"
    _csv(path)
    with StreamingSignalQuoteJournal(
        [one], max_signals=1, max_captured_quotes=1,
    ) as journal:
        journal.add_signal("A", _event(one, 2), horizon_minutes=10)
        with pytest.raises(ValueError, match="SIGNAL_EVENT_LIMIT"):
            journal.add_signal("A", _event(one, 3))
        assert journal.count("A") == 1
        with pytest.raises(ValueError, match="CAPTURED_QUOTE_LIMIT"):
            journal.capture_quotes(path)
        with pytest.raises(RuntimeError, match="ALREADY_CAPTURED"):
            journal.capture_quotes(path)
        with pytest.raises(RuntimeError, match="NOT_CAPTURED"):
            list(journal.iter_events("A"))


def test_journal_out_of_order_signal_and_bad_configuration(tmp_path):
    one = _spec("BTC-CE")
    with StreamingSignalQuoteJournal([one]) as journal:
        journal.add_signal("A", _event(one, 8))
        with pytest.raises(ValueError, match="OUT_OF_ORDER"):
            journal.add_signal("A", _event(one, 4))
        with pytest.raises(ValueError, match="config"):
            journal.add_signal("", _event(one, 9))
        with pytest.raises(ValueError, match="horizon"):
            journal.add_signal("A", _event(one, 9), horizon_minutes=-1)
        with pytest.raises(ValueError, match="OPTION_NOT_IN"):
            journal.add_signal("A", _event(_spec("UNLISTED-CE"), 9))
        assert journal.count("A") == 1


def test_journal_preserves_horizon_none_and_inclusive_end(tmp_path):
    one = _spec("BTC-CE")
    rows = tmp_path / "quotes.csv"
    _csv(rows)
    original = [_event(one, 2)]
    capture_quotes_positional(rows, original, horizon_minutes=None)
    with StreamingSignalQuoteJournal([one]) as journal:
        journal.add_signal("A", _event(one, 2), horizon_minutes=None)
        journal.capture_quotes(rows)
        _compare_fields(original[0], next(journal.iter_events("A")))


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_journal_rejects_invalid_signal_cap(value):
    with pytest.raises(ValueError, match="max_signals"):
        StreamingSignalQuoteJournal([], max_signals=value)


def test_journal_rejects_duplicate_option_catalog_symbols():
    with pytest.raises(ValueError, match="DUPLICATE"):
        StreamingSignalQuoteJournal([_spec("BTC-CE"), _spec("BTC-CE")])


def test_journal_closed_guards(tmp_path):
    with StreamingSignalQuoteJournal([]) as journal:
        pass
    with pytest.raises(RuntimeError, match="CLOSED"):
        journal.snapshot_metrics()
    with pytest.raises(RuntimeError, match="CLOSED"):
        list(journal.iter_events("A"))
