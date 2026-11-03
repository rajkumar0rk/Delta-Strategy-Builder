"""All-row parity and fail-closed isolation of indicator streaming benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.benchmark_indicator_chunks import (
    benchmark_indicator_chunks, compare_indicator_csv,
)


def test_indicator_csv_detects_flags_timestamps_and_float_drift(tmp_path):
    original = tmp_path / "a.csv"
    candidate = tmp_path / "b.csv"
    original.write_text(
        "timestamp,close,entry_signal,direction\n"
        "2026-09-01,1.0000000000,True,CALL\n"
        "2026-09-02,2.0,False,\n", encoding="utf-8",
    )
    candidate.write_text(
        "timestamp,close,entry_signal,direction\n"
        "2026-09-01,1.00000000005,True,CALL\n"
        "2026-09-02,2.0,False,\n", encoding="utf-8",
    )
    assert compare_indicator_csv(original, candidate) == []
    candidate.write_text(candidate.read_text().replace("True", "False"),
                         encoding="utf-8")
    assert any("entry_signal" in error for error in compare_indicator_csv(
        original, candidate,
    ))
    candidate.write_text(candidate.read_text().replace(
        "2026-09-02", "2026-09-03"
    ), encoding="utf-8")
    assert any("timestamp" in error for error in compare_indicator_csv(
        original, candidate,
    ))
    candidate.write_text(candidate.read_text() + "2026-09-04,2.0,False,\n",
                         encoding="utf-8")
    assert any("row count" in error for error in compare_indicator_csv(
        original, candidate,
    ))


def test_balanced_indicator_benchmark_checks_every_mode(monkeypatch, tmp_path):
    order = []

    def fake_run(argv, check):
        assert check
        mode = argv[argv.index("--mode") + 1]
        order.append(mode)
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(
            "timestamp,close,entry_signal\n"
            "2026-09-01,1.0,False\n"
            "2026-09-02,2.0,True\n",
            encoding="utf-8",
        )
        meta = Path(argv[argv.index("--metadata") + 1])
        meta.write_text(json.dumps({
            "mode": mode,
            "elapsed_seconds": 5 if mode == "FULL" else 4,
            "peak_process_rss_kib": 99000 if mode == "FULL" else 74000,
            "rows": 2,
            "retained_context_max_rows": None if mode == "FULL" else 33,
            "csv_bytes": output.stat().st_size,
        }), encoding="utf-8")

    monkeypatch.setattr(
        "backtest.benchmark_indicator_chunks.subprocess.run", fake_run,
    )
    result = benchmark_indicator_chunks(
        tmp_path, tmp_path / "report",
        rounds=2, chunk_rows=64, max_session_rows=4096,
    )
    assert order == [
        "FULL", "CHUNKED", "CHUNKED", "FULL",
        "CHUNKED", "FULL", "FULL", "CHUNKED",
    ]
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert result["statistics"]["FULL"]["runs"] == 4
    assert result["statistics"]["CHUNKED"]["max_context_rows"] == 33
    assert result["statistics"]["CHUNKED"]["median_peak_rss_kib"] == 74000
    assert (tmp_path / "report" / "reference-full-indicators.csv").exists()
    assert not list((tmp_path / "report").glob("round-*-indicators.csv"))


@pytest.mark.parametrize("parameter,bad", [
    ("rounds", 0), ("rounds", True),
    ("chunk_rows", -1), ("chunk_rows", 1.5),
    ("max_session_rows", 0), ("max_session_rows", False),
])
def test_indicator_benchmark_rejects_invalid_inputs(tmp_path, parameter, bad):
    params = {parameter: bad}
    with pytest.raises(ValueError, match=parameter):
        benchmark_indicator_chunks(
            tmp_path, tmp_path / "report", **params,
        )
