"""Fail-closed benchmark comparison and ABBA/BAAB order regression."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.benchmark_incremental_signals import (
    _compare_value, benchmark_incremental_signals, compare_jsonl,
)


def test_signal_benchmark_requires_exact_nanosecond_timestamps():
    errors = []
    _compare_value({
        "timestamp_ns": 1_900_000_000_000_000_000,
        "entry": True, "premium": 1.000000000001,
    }, {
        "timestamp_ns": 1_900_000_000_000_000_001,
        "entry": True, "premium": 1.000000000002,
    }, "event", errors)
    assert len(errors) == 1
    assert "timestamp_ns" in errors[0]


def test_signal_benchmark_checks_all_events_and_decision_order(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(
        '{"timestamp_ns":100,"status":"QUALIFIED"}\n'
        '{"timestamp_ns":200,"status":"REJECTED"}\n', encoding="utf-8",
    )
    b.write_text(
        '{"timestamp_ns":100,"status":"QUALIFIED"}\n'
        '{"timestamp_ns":200,"status":"QUALIFIED"}\n', encoding="utf-8",
    )
    count, examples = compare_jsonl(a, b)
    assert count == 1 and "status" in examples[0]
    b.write_text(
        '{"timestamp_ns":100,"status":"QUALIFIED"}\n', encoding="utf-8",
    )
    count, examples = compare_jsonl(a, b)
    assert count == 1 and "row count" in examples[0]


def test_signal_benchmark_balances_orders_and_checks_both_configs(
    monkeypatch, tmp_path,
):
    from backtest import benchmark_incremental_signals as benchmark

    order = []

    def fake_run(argv, check):
        assert check
        mode = argv[argv.index("--mode") + 1]
        order.append(mode)
        target = Path(argv[argv.index("--output") + 1])
        for config in ("0", "1"):
            for kind in ("events", "decisions"):
                (target / f"config-{config}-{kind}.jsonl").write_text(
                    '{"timestamp_ns":1900000000000000000,"direction":"CALL"}\n',
                    encoding="utf-8",
                )
        meta = Path(argv[argv.index("--metadata") + 1])
        meta.write_text(json.dumps({
            "mode": mode,
            "elapsed_seconds": 10 if mode == "FULL" else 8,
            "peak_process_rss_kib": 95000 if mode == "FULL" else 80000,
            "counts": {
                "0": {"events": 1, "decision_events": 1, "diagnostics": {}},
                "1": {"events": 1, "decision_events": 1, "diagnostics": {}},
            },
        }), encoding="utf-8")

    monkeypatch.setattr(
        benchmark.subprocess, "run", fake_run,
    )
    result = benchmark_incremental_signals(
        tmp_path, "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z",
        tmp_path / "results", rounds=2,
    )
    assert order == [
        "FULL", "INCREMENTAL", "INCREMENTAL", "FULL",
        "INCREMENTAL", "FULL", "FULL", "INCREMENTAL",
    ]
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert result["statistics"]["FULL"]["runs"] == 4
    assert result["statistics"]["INCREMENTAL"]["median_peak_rss_kib"] == 80000


@pytest.mark.parametrize("arg,value", [
    ("rounds", 0), ("rounds", True), ("rounds", 11),
    ("chunk_rows", 0), ("chunk_rows", 0.5),
    ("max_session_rows", False), ("max_session_rows", -1),
])
def test_signal_benchmark_rejects_invalid_controls(tmp_path, arg, value):
    with pytest.raises(ValueError, match=arg):
        benchmark_incremental_signals(
            tmp_path, "2026-09-01", "2026-09-15",
            tmp_path / "out", **{arg:value},
        )
