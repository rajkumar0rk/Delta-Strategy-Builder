import json
from pathlib import Path

import pytest
from backtest.benchmark_legacy_run import benchmark


def test_optional_indicator_profile_preserves_original_two_modes(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, check):
        assert check
        calls.append(list(argv))
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps({
            "result": {"trades": [], "decision_events": [], "results": []},
            "elapsed_seconds": .25,
            "peak_process_rss_kib": 2048,
        }))
    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run", fake_run)
    report = benchmark(tmp_path, "2026-09-01", "2026-09-02",
                       tmp_path / "report", indicator_chunk_rows=17)
    assert report["parity_passed"]
    assert list(report["measurements"]) == [
        "MEMORY", "SQLITE", "SQLITE_STREAMED_INDICATORS"
    ]
    assert len(calls) == 3
    assert all("--indicator-chunk-rows" not in call for call in calls[:2])
    assert calls[2][calls[2].index("--indicator-chunk-rows")+1] == "17"


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_indicator_chunk_rows(value, tmp_path):
    with pytest.raises(ValueError, match="indicator_chunk_rows"):
        benchmark(tmp_path, "2026-09-01", "2026-09-02",
                  tmp_path / "report", indicator_chunk_rows=value)
