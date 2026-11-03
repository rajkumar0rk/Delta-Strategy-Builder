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


def test_bucket_matching_benchmark_passes_config_into_child_process(
    monkeypatch, tmp_path,
):
    from backtest import benchmark_signal_quote_journal as benchmark
    modes_and_flags = []

    def fake_run(argv, check):
        assert check
        mode = argv[argv.index("--mode") + 1]
        flag = argv[argv.index("--journal-matching") + 1]
        assert flag == "BUCKET_CACHE"
        assert argv[argv.index("--bucket-minutes") + 1] == "10"
        assert argv[argv.index("--max-cache-buckets") + 1] == "2"
        assert argv[argv.index("--max-cached-candidates") + 1] == "3"
        modes_and_flags.append((mode, flag))
        root = Path(argv[argv.index("--output") + 1])
        for name in ("0", "1"):
            _write(root / f"config-{name}-events.jsonl")
        metadata = Path(argv[argv.index("--metadata") + 1])
        metadata.write_text(json.dumps({
            "mode": mode, "elapsed_seconds": 5.0,
            "peak_process_rss_kib": 81000,
            "counts": {"0": 1, "1": 1},
            "captured_quote_rows": 2,
            "lookup_metrics": {
                "matching_mode": flag, "db_queries": 1,
            } if mode == "JOURNAL" else None,
        }), encoding="utf-8")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)
    result = benchmark_signal_quote_journal(
        tmp_path, "2026-09-01", "2026-09-15", tmp_path / "out",
        rounds=1, journal_matching="BUCKET_CACHE",
        bucket_minutes=10, max_cache_buckets=2,
        max_cached_candidates=3,
    )
    assert result["parity_passed"]
    assert result["journal_matching"] == "BUCKET_CACHE"
    assert [item[0] for item in modes_and_flags] == [
        "FULL", "JOURNAL", "JOURNAL", "FULL",
    ]
    assert result["measurements"][1]["lookup_metrics"]["db_queries"] == 1


@pytest.mark.parametrize("settings", [
    {"journal_matching": "BAD"},
    {"bucket_minutes": 0}, {"bucket_minutes": 1.5},
    {"max_cache_buckets": 0}, {"max_cache_buckets": True},
    {"max_cached_candidates": -1}, {"max_cached_candidates": False},
])
def test_journal_benchmark_rejects_invalid_match_settings(tmp_path, settings):
    with pytest.raises(ValueError):
        benchmark_signal_quote_journal(
            tmp_path, "a", "b", tmp_path / "out", **settings,
        )


def test_symbol_interval_benchmark_passes_bounded_controls_to_children(
    monkeypatch, tmp_path,
):
    from backtest import benchmark_signal_quote_journal as benchmark

    modes = []

    def fake_run(argv, check):
        assert check
        mode = argv[argv.index("--mode") + 1]
        modes.append(mode)
        assert argv[argv.index("--journal-matching") + 1] == "SYMBOL_INDEX"
        assert argv[argv.index("--max-cached-symbols") + 1] == "17"
        assert argv[argv.index("--max-cached-candidates") + 1] == "211"
        target = Path(argv[argv.index("--output") + 1])
        for config in ("0", "1"):
            _write(target / f"config-{config}-events.jsonl")
        metadata = Path(argv[argv.index("--metadata") + 1])
        metadata.write_text(json.dumps({
            "mode": mode, "elapsed_seconds": 2.0,
            "peak_process_rss_kib": 84000,
            "counts": {"0": 1, "1": 1}, "captured_quote_rows": 2,
            "lookup_metrics": {
                "matching_mode": "SYMBOL_INDEX",
                "db_queries": 2,
                "peak_cached_symbols": 2,
                "peak_cached_candidates": 2,
            } if mode == "JOURNAL" else None,
        }), encoding="utf-8")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)
    result = benchmark_signal_quote_journal(
        tmp_path, "2026-09-01", "2026-09-15",
        tmp_path / "out", rounds=1,
        journal_matching="SYMBOL_INDEX",
        max_cached_symbols=17, max_cached_candidates=211,
    )
    assert result["parity_passed"]
    assert result["journal_matching"] == "SYMBOL_INDEX"
    assert result["max_cached_symbols"] == 17
    assert modes == ["FULL", "JOURNAL", "JOURNAL", "FULL"]
    assert result["measurements"][1]["lookup_metrics"]["db_queries"] == 2


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_benchmark_rejects_bad_cached_symbol_limit(tmp_path, value):
    with pytest.raises(ValueError, match="max_cached_symbols"):
        benchmark_signal_quote_journal(
            tmp_path, "2026-09-01", "2026-09-15",
            tmp_path / "out", max_cached_symbols=value,
        )
