"""Spool vs memory benchmark is independent and fails closed on report drift."""
import json
from pathlib import Path

import pytest

from backtest.benchmark_report_streaming import benchmark_streamed_reports


def test_abba_baab_report_comparison_and_memory_metrics(monkeypatch, tmp_path):
    sequence = []

    def fake_run(argv, check):
        assert check
        assert "--child" in argv
        mode = argv[argv.index("--mode") + 1]
        sequence.append(mode)
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({
            "results": [{"scenario": {"name": "H6"}, "metrics": {"trades": 1}}],
            "trades": [{"pnl_usd": 0.55, "fees_usd": 0.03}],
            "execution_attempts": [{"quantity": 5}],
            "decision_events": [{"reason": "TRADE_ACCEPTED"}],
        }))
        metadata = Path(argv[argv.index("--metadata") + 1])
        metadata.write_text(json.dumps({
            "mode": mode,
            "elapsed_seconds": 10 if mode == "MEMORY" else 8,
            "peak_process_rss_kib": 98000 if mode == "MEMORY" else 92000,
            "report_bytes": output.stat().st_size,
            "counts": {"trades": 1, "execution_attempts": 1, "decision_events": 1},
        }))

    monkeypatch.setattr("backtest.benchmark_report_streaming.subprocess.run", fake_run)
    result = benchmark_streamed_reports(
        tmp_path, "2026-09-01", "2026-09-15",
        tmp_path / "results", rounds=2,
    )
    assert sequence == [
        "MEMORY", "STREAMED", "STREAMED", "MEMORY",
        "STREAMED", "MEMORY", "MEMORY", "STREAMED",
    ]
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert result["statistics"]["MEMORY"]["median_seconds"] == 10
    assert result["statistics"]["STREAMED"]["median_peak_rss_kib"] == 92000
    assert result["median_time_reduction_percent"] == 20
    assert not list((tmp_path / "results").glob("*-metrics.json"))
    assert not list((tmp_path / "results").glob("round-*-report.json"))


def test_streamed_report_mismatch_keeps_debugging_artifact(monkeypatch, tmp_path):
    def fake_run(argv, check):
        mode = argv[argv.index("--mode") + 1]
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps({
            "trades": [{"pnl_usd": 1.0 if mode == "MEMORY" else 2.0}]
        }))
        metadata = Path(argv[argv.index("--metadata") + 1])
        metadata.write_text(json.dumps({
            "mode": mode, "elapsed_seconds": 3,
            "peak_process_rss_kib": 90000,
            "report_bytes": output.stat().st_size,
            "counts": {"trades": 1, "execution_attempts": 0, "decision_events": 0},
        }))

    monkeypatch.setattr("backtest.benchmark_report_streaming.subprocess.run", fake_run)
    folder = tmp_path / "results"
    with pytest.raises(ValueError, match="RESULT_PARITY_MISMATCH"):
        benchmark_streamed_reports(
            tmp_path, "2026-09-01", "2026-09-15", folder, rounds=1,
        )
    saved = json.loads((folder / "benchmark.json").read_text())
    assert not saved["parity_passed"]
    assert saved["difference_count"] == 2
    assert list(folder.glob("*streamed-report.json"))
    assert (folder / "reference-memory-report.json").exists()


@pytest.mark.parametrize("bad", [0, -1, 11, True, 1.5])
def test_bad_rounds_fail_closed(tmp_path, bad):
    with pytest.raises(ValueError, match="rounds"):
        benchmark_streamed_reports(
            tmp_path, "2026-09-01", "2026-09-15",
            tmp_path / "out", rounds=bad,
        )
