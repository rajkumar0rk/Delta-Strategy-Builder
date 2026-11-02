"""Offline alternating quote parser A/B orchestration tests."""
import json
from pathlib import Path

import pytest

from backtest.benchmark_positional_ab import benchmark_positional_ab


def test_abba_baab_balanced_order_parity_and_statistics(monkeypatch, tmp_path):
    order = []

    def fake_subprocess_run(argv, check):
        assert check is True
        assert argv[argv.index("--mode") + 1] == "MEMORY"
        assert argv[argv.index("--algorithm") + 1] == "LEGACY"
        parser = argv[argv.index("--quote-csv-parser") + 1]
        order.append(parser)
        target = Path(argv[argv.index("--output") + 1])
        target.write_text(json.dumps({
            "result": {
                "trades": [{"pnl_usd": 1.2}],
                "results": [{"metrics": {"trades": 1}}],
                "execution_attempts": [{}],
            },
            "elapsed_seconds": 10.0 if parser == "DICT" else 8.0,
            "peak_process_rss_kib": 10240,
        }))

    monkeypatch.setattr(
        "backtest.benchmark_positional_ab.subprocess.run", fake_subprocess_run
    )
    output = tmp_path / "results"
    result = benchmark_positional_ab(
        tmp_path, "2026-09-01", "2026-09-08", output, rounds=2
    )
    assert order == [
        "DICT", "POSITIONAL", "POSITIONAL", "DICT",
        "POSITIONAL", "DICT", "DICT", "POSITIONAL",
    ]
    assert result["parity_passed"] is True
    assert result["difference_count"] == 0
    assert result["baseline_trade_count"] == 1
    assert result["baseline_execution_attempt_count"] == 1
    assert result["statistics"]["DICT"]["median_seconds"] == 10.0
    assert result["statistics"]["POSITIONAL"]["median_seconds"] == 8.0
    assert result["median_time_reduction_percent"] == pytest.approx(20.0)
    assert len(result["measurements"]) == 8
    assert (output / "benchmark.json").exists()
    assert (output / "reference-dict-report.json").exists()
    assert not list(output.glob("*-child.json"))


def test_ab_benchmark_fails_closed_when_reports_differ(monkeypatch, tmp_path):
    count = 0

    def fake_subprocess_run(argv, check):
        nonlocal count
        count += 1
        target = Path(argv[argv.index("--output") + 1])
        target.write_text(json.dumps({
            "result": {
                "trades": [{"pnl_usd": 1.2 if count != 2 else -2.0}],
                "execution_attempts": [],
            },
            "elapsed_seconds": 1.0,
            "peak_process_rss_kib": None,
        }))
    monkeypatch.setattr(
        "backtest.benchmark_positional_ab.subprocess.run", fake_subprocess_run
    )
    with pytest.raises(ValueError, match="RESULT_PARITY_MISMATCH"):
        benchmark_positional_ab(
            tmp_path, "2026-09-01", "2026-09-08", tmp_path / "results",
            rounds=1
        )
    saved = json.loads(
        (tmp_path / "results" / "benchmark.json").read_text()
    )
    assert saved["difference_count"] == 1
    assert saved["parity_passed"] is False


@pytest.mark.parametrize("rounds", [0, -1, 13, 1.5, True])
def test_invalid_round_count_rejected(rounds, tmp_path):
    with pytest.raises(ValueError, match="rounds"):
        benchmark_positional_ab(
            tmp_path, "2026-09-01", "2026-09-08",
            tmp_path / "results", rounds=rounds,
        )
