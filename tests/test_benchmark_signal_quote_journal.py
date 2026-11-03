"""Quote-journal benchmark must fail closed on any reordered or changed quote."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.benchmark_signal_quote_journal import (
    benchmark_signal_quote_journal, compare_event_records,
)


def _write(path: Path, *, bid: float=1.5, timestamp=123):
    path.write_text(json.dumps({
        "timestamp_ns": timestamp, "direction": "CALL",
        "option": {"symbol": "BTC-CE"},
        "quotes": [{
            "timestamp_ns": 456.0, "bid": bid, "ask": 1.7,
            "bid_size": 5.0, "ask_size": 7.0,
            "volume": 22.0, "open_interest": 9.0,
        }],
    }) + "\n", encoding="utf-8")


def test_quote_journal_benchmark_checks_all_fields_and_row_counts(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(a)
    _write(b)
    assert compare_event_records(a, b) == (0, [])
    _write(b, bid=1.50001)
    assert any("bid" in item for item in compare_event_records(a, b)[1])
    _write(b, timestamp=124)
    assert any("timestamp_ns" in item for item in compare_event_records(a, b)[1])
    b.write_text("", encoding="utf-8")
    assert any("row count" in item for item in compare_event_records(a, b)[1])


def test_journal_benchmark_uses_balanced_modes_and_catches_count_changes(
    monkeypatch, tmp_path,
):
    from backtest import benchmark_signal_quote_journal as benchmark
    seen = []

    def fake_run(argv, check):
        assert check
        mode = argv[argv.index("--mode") + 1]
        seen.append(mode)
        root = Path(argv[argv.index("--output") + 1])
        for config in ("0", "1"):
            _write(root / f"config-{config}-events.jsonl")
        metadata = Path(argv[argv.index("--metadata") + 1])
        metadata.write_text(json.dumps({
            "mode": mode, "elapsed_seconds": 5.0,
            "peak_process_rss_kib": 85000 if mode == "FULL" else 80000,
            "counts": {"0": 1, "1": 1}, "captured_quote_rows": 2,
        }), encoding="utf-8")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)
    result = benchmark_signal_quote_journal(
        tmp_path, "2026-09-01", "2026-09-15",
        tmp_path / "out", rounds=2,
    )
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert seen == [
        "FULL", "JOURNAL", "JOURNAL", "FULL",
        "JOURNAL", "FULL", "FULL", "JOURNAL",
    ]
    assert result["statistics"]["JOURNAL"]["median_peak_rss_kib"] == 80000
    assert (tmp_path / "out" / "reference-full" / "config-0-events.jsonl").exists()
    assert not list((tmp_path / "out").glob("round-*"))


@pytest.mark.parametrize("parameter,value", [
    ("rounds", 0), ("rounds", True), ("rounds", 11),
    ("chunk_rows", 0), ("chunk_rows", 1.5),
    ("max_session_rows", -1), ("max_session_rows", True),
])
def test_journal_benchmark_rejects_bad_settings(tmp_path, parameter, value):
    with pytest.raises(ValueError, match=parameter):
        benchmark_signal_quote_journal(
            tmp_path, "a", "b", tmp_path / "out",
            **{parameter:value},
        )
