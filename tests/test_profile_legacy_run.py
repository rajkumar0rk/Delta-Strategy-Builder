import json
from pathlib import Path
import pytest

from backtest.profile_legacy_run import profile_dataset


def test_profiler_records_stage_counts_and_stats(monkeypatch, tmp_path):
    def fake_run(directory, *, start, end, scenario_set, stage_observer):
        stage_observer("INDICATORS_AND_CSV", 0.12)
        stage_observer("SIGNAL_EVALUATION", 0.34)
        return {
            "trades": [{"pnl": 4}], "execution_attempts": [{}],
            "decision_events": [{}, {}],
            "raw_signals_with_contract": 3,
            "results": [{"scenario": {"name": "H6"}, "metrics": {"trades": 1}}],
        }
    monkeypatch.setattr("backtest.profile_legacy_run.run_dataset", fake_run)
    value = profile_dataset(tmp_path, "2026-09-01", "2026-09-02", tmp_path / "result")
    assert value["trades"] == 1
    assert value["execution_attempts"] == 1
    assert value["signals_with_contract"] == 3
    assert [x["stage"] for x in value["stages"]] == [
        "INDICATORS_AND_CSV", "SIGNAL_EVALUATION"
    ]
    assert (tmp_path / "result" / "cpu.pstats").exists()
    assert json.loads((tmp_path / "result" / "profile.json").read_text())["trades"] == 1


def test_invalid_top_functions_does_not_start_runner(tmp_path):
    for value in (0, 201):
        with pytest.raises(ValueError, match="top_functions"):
            profile_dataset(tmp_path, "2026-09-01", "2026-09-02",
                            tmp_path / "result", top_functions=value)
