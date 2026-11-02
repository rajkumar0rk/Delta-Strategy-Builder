import json
from pathlib import Path

from backtest.benchmark_positional_ab import benchmark_positional_ab


def test_compact_indicator_ab_isolates_categorical_direction_mode(monkeypatch, tmp_path):
    order = []

    def run(argv, check):
        assert check
        assert argv[argv.index("--mode") + 1] == "MEMORY"
        assert argv[argv.index("--algorithm") + 1] == "LEGACY"
        assert argv[argv.index("--quote-csv-parser") + 1] == "POSITIONAL"
        assert "--positional-bar-lookup" in argv
        assert "--trim-simulation-frame" in argv
        compact = "--compact-indicator-directions" in argv
        order.append(compact)
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps({
            "result": {
                "trades": [{"pnl_usd": 3.0, "fees_usd": 0.06}],
                "execution_attempts": [{"filled_quantity": 5}],
                "decision_events": [{"reason": "TRADE_ACCEPTED"}],
            },
            "elapsed_seconds": 9 if compact else 10,
            "peak_process_rss_kib": 88000 if compact else 89000,
        }))

    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run", run)
    result = benchmark_positional_ab(
        tmp_path, "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z",
        tmp_path / "out", comparison="INDICATOR_COMPACT", rounds=2,
    )
    assert order == [False, True, True, False, True, False, False, True]
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert result["baseline_variant"] == "POSITIONAL_FRAME_TRIM"
    assert result["candidate_variant"] == "POSITIONAL_COMPACT"
    assert result["measurements"][0]["compact_indicator_directions"] is False
    assert result["measurements"][1]["compact_indicator_directions"] is True
    assert result["median_time_reduction_percent"] == 10.0
