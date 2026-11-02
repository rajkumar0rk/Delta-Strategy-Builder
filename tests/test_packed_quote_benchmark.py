"""Benchmark metadata must describe exact SQLite/quote-spool settings."""
import json
from pathlib import Path

from backtest.benchmark_legacy_run import benchmark


def test_packed_sqlite_profiles_are_opt_in_and_have_matching_inputs(monkeypatch,tmp_path):
    calls = []
    def fake_run(argv,check):
        assert check
        calls.append(list(argv))
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
            "result": {"trades":[{"pnl_usd":2.25}], "results":[],
                       "execution_attempts":[{}], "decision_events":[{}]},
            "elapsed_seconds":3.0, "peak_process_rss_kib":2500,
        }))
    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run",fake_run)
    summary=benchmark(tmp_path,"2026-09-01","2026-09-08",
                      tmp_path/"results",include_packed_sqlite_profile=True)
    assert summary["parity_passed"] and summary["difference_count"]==0
    assert list(summary["measurements"])==[
        "MEMORY","SQLITE","SQLITE_POSITIONAL_JSON","SQLITE_POSITIONAL_PACKED",
    ]
    settings=[]
    for argv in calls:
        value=lambda flag: argv[argv.index(flag)+1]
        settings.append((
            value("--mode"),value("--algorithm"),
            value("--quote-csv-parser"),value("--quote-spool-encoding"),
            "--positional-bar-lookup" in argv,
        ))
    assert settings==[
        ("MEMORY","LEGACY","DICT","JSON",False),
        ("SQLITE","SWEEP","DICT","JSON",False),
        ("SQLITE","SWEEP","POSITIONAL","JSON",True),
        ("SQLITE","SWEEP","POSITIONAL","PACKED",True),
    ]
    assert summary["measurements"]["SQLITE_POSITIONAL_PACKED"]["quote_spool_encoding"]=="PACKED"
