"""Python-retained report sizes and optional stage attribution do not change reports."""
import json

from backtest.profile_legacy_run import profile_dataset
from backtest.report_memory_inventory import (
    deep_json_tree_bytes, report_retained_sizes,
)


def test_report_memory_tree_counts_shared_references_once_and_handles_cycles():
    shared = [{"reason": "ACCEPTED", "pnl_usd": 3.5}]
    report = {"trades": shared, "alias": shared, "decision_events": []}
    total = deep_json_tree_bytes(report)
    separate = (
        deep_json_tree_bytes({"trades": shared})
        + deep_json_tree_bytes({"alias": shared})
    )
    assert 0 < total < separate + deep_json_tree_bytes({"decision_events": []})
    summary = report_retained_sizes(report)
    assert summary["total_unique_python_bytes"] == total
    assert summary["fields"]["trades"] == summary["fields"]["alias"]
    cycle = []
    cycle.append(cycle)
    assert deep_json_tree_bytes(cycle) > 0


def test_profile_with_allocations_records_stage_rss_sources_and_report_bytes(
    monkeypatch, tmp_path,
):
    output = tmp_path / "profile"

    def fake_run(directory, *, start, end, scenario_set,
                 stage_observer, retention_observer):
        rows = [{"payload": index} for index in range(25)]
        stage_observer("INDICATORS_AND_CSV", 0.12)
        retention_observer("INDICATORS_AND_CSV", {
            "indicator_rows": 25, "indicator_frame_bytes": 2048,
        })
        rows.extend({"payload": index} for index in range(25, 60))
        stage_observer("SIGNAL_EVALUATION", 0.25)
        retention_observer("SIGNAL_EVALUATION", {
            "signal_events": 3, "configuration_decision_events": 1,
        })
        return {
            "trades": [{"pnl_usd": 4.0, "fees_usd": 0.05}],
            "execution_attempts": [{"quantity": 5}],
            "decision_events": [{"stage": "SIGNAL", "reason": "ACCEPTED"}],
            "raw_signals_with_contract": 3,
            "results": [
                {"scenario": {"name": "H6"}, "metrics": {"trades": 1}}
            ],
        }

    monkeypatch.setattr("backtest.profile_legacy_run.run_dataset", fake_run)
    summary = profile_dataset(
        tmp_path, "2026-09-01", "2026-09-15", output,
        track_allocations=True,
    )
    assert summary["trades"] == 1
    assert summary["decision_events"] == 1
    assert summary["peak_traced_python_bytes"] > 0
    assert summary["retention_inventory"][0]["indicator_frame_bytes"] == 2048
    assert len(summary["stages"]) == 2
    for stage in summary["stages"]:
        assert stage["python_traced_current_bytes"] >= 0
        assert stage["python_traced_peak_bytes"] >= stage["python_traced_current_bytes"]
        assert isinstance(stage["python_allocation_changes"], list)
    report_bytes = summary["report_retained_python_bytes"]
    assert report_bytes["total_unique_python_bytes"] > 0
    assert report_bytes["fields"]["trades"] > 0
    assert report_bytes["fields"]["decision_events"] > 0
    assert (output / "cpu.pstats").is_file()
    saved = json.loads((output / "profile.json").read_text())
    assert saved["report_retained_python_bytes"] == report_bytes
    assert saved["retention_inventory"] == summary["retention_inventory"]
