"""Offline independent-profile benchmark orchestration (no downloads)."""
import json
from pathlib import Path

from backtest.benchmark_legacy_run import benchmark


def test_three_profile_benchmark_parity_and_retention_flags(monkeypatch, tmp_path):
    calls = []

    def fake_subprocess_run(argv, check):
        assert check is True
        calls.append(list(argv))
        target = Path(argv[argv.index("--output") + 1])
        target.write_text(json.dumps({
            "result": {"trades": [{"entry": 100, "pnl_usd": 1.5}],
                       "results": [{"net_pnl_usd": 1.5}],
                       "decision_events": []},
            "elapsed_seconds": 1.0,
            "peak_process_rss_kib": 2048,
        }), encoding="utf-8")

    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run", fake_subprocess_run)
    outcome = benchmark(
        tmp_path / "historical", "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z", tmp_path / "report",
        retain_decision_events=False, include_pruned_profile=True,
    )
    assert outcome["parity_passed"]
    assert outcome["difference_count"] == 0
    assert set(outcome["measurements"]) == {"MEMORY", "SQLITE", "SQLITE_PRUNED"}
    assert len(calls) == 3
    assert all("--omit-decision-events" in args for args in calls)
    assert "--prune-inactive-instruments" not in calls[0]
    assert "--prune-inactive-instruments" not in calls[1]
    assert "--prune-inactive-instruments" in calls[2]
    assert json.loads((tmp_path / "report" / "benchmark.json").read_text())["parity_passed"]


def test_default_benchmark_still_uses_two_modes(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, check):
        calls.append(list(argv))
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps({
            "result": {"trades": [], "decision_events": []},
            "elapsed_seconds": 0.1, "peak_process_rss_kib": None
        }), encoding="utf-8")

    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run", fake_run)
    result = benchmark(tmp_path, "2026-09-01", "2026-09-02", tmp_path / "report")
    assert len(calls) == 2
    assert result["parity_passed"]
    assert all("--omit-decision-events" not in args for args in calls)
