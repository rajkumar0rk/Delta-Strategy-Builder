import json
from pathlib import Path

from backtest.benchmark_positional_ab import benchmark_positional_ab


def test_retention_abba_uses_same_parser_and_bars_for_both_modes(monkeypatch,tmp_path):
    invocations = []
    def run(argv, check):
        assert check is True
        parser = argv[argv.index("--quote-csv-parser") + 1]
        mode = argv[argv.index("--mode") + 1]
        algorithm = argv[argv.index("--algorithm") + 1]
        assert parser == "POSITIONAL"
        assert mode == "MEMORY"
        assert algorithm == "LEGACY"
        assert "--positional-bar-lookup" in argv
        enabled = "--release-completed-configurations" in argv
        invocations.append(enabled)
        target = Path(argv[argv.index("--output") + 1])
        target.write_text(json.dumps({
            "result": {
                "trades": [{"pnl_usd": 4.2, "fees_usd": 0.03}],
                "execution_attempts": [{}],
                "decision_events": [{"stage": "EXECUTION"}],
            },
            "elapsed_seconds": 10 if not enabled else 8,
            "peak_process_rss_kib": 98000 if not enabled else 94000,
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run",run)
    result = benchmark_positional_ab(
        tmp_path, "2026-09-01", "2026-09-08", tmp_path/"result",
        comparison="RETENTION", rounds=2,
    )
    assert invocations == [False,True,True,False,True,False,False,True]
    assert result["parity_passed"]
    assert result["baseline_variant"] == "POSITIONAL_BAR_LOOKUP"
    assert result["candidate_variant"] == "POSITIONAL_RELEASE"
    assert result["median_time_reduction_percent"] == 20
    assert all(not record["difference_count"] for record in result["measurements"])
    assert result["measurements"][1]["release_completed_configurations"]
    assert not result["measurements"][0]["release_completed_configurations"]
