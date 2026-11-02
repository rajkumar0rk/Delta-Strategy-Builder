import json
from pathlib import Path

import pytest
from backtest.benchmark_memory_growth import _horizons, benchmark_memory_growth


def test_multi_window_memory_inventory_and_report_parity(monkeypatch, tmp_path):
    commands = []

    def run(argv, check):
        assert check
        commands.append(argv)
        mode = argv[argv.index("--mode") + 1]
        path = Path(argv[argv.index("--output") + 1])
        assert "--memory-inventory" in argv
        assert "--positional-bar-lookup" in argv
        path.write_text(json.dumps({
            "result": {"trades": [{"pnl_usd": 1.5}],
                       "execution_attempts": [{}], "decision_events": []},
            "elapsed_seconds": 5.0,
            "peak_process_rss_kib": 88000,
            "phase_memory": [{"stage": "INDICATORS_AND_CSV",
                              "cumulative_peak_rss_kib": 78000}],
            "retention_inventory": [{"stage": "INDICATORS_AND_CSV",
                                     "indicator_rows": 100,
                                     "indicator_frame_bytes": 9000}],
            "quote_spool_metrics": {"captured_quote_rows": 120}
                if mode == "SQLITE" else None,
        }))
    monkeypatch.setattr("backtest.benchmark_memory_growth.subprocess.run", run)
    result = benchmark_memory_growth(
        tmp_path, "2026-09-01T00:00:00Z", tmp_path/"report",
        days=(1, 7), modes=("PACKED", "MEMORY"),
    )
    assert result["parity_passed"]
    assert len(commands) == 4
    assert result["modes"] == ["MEMORY", "PACKED"]
    assert result["windows"][1]["end"] == "2026-09-08T00:00:00Z"
    assert result["windows"][0]["modes"]["PACKED"]["quote_spool_metrics"]["captured_quote_rows"] == 120
    assert not list((tmp_path/"report").glob("*-child.json"))
    assert json.loads((tmp_path/"report"/"benchmark.json").read_text())["parity_passed"]


@pytest.mark.parametrize("raw", ["", "1,1", "0", "a", "366"])
def test_invalid_days(raw):
    with pytest.raises(ValueError, match="days"):
        _horizons(raw)


def test_invalid_start_and_modes(tmp_path):
    with pytest.raises(ValueError, match="start"):
        benchmark_memory_growth(tmp_path, "2026-09-01T00:00:00", tmp_path/"x")
    with pytest.raises(ValueError, match="modes"):
        benchmark_memory_growth(
            tmp_path, "2026-09-01T00:00:00Z", tmp_path/"x",
            modes=("PACKED", "PACKED"),
        )
