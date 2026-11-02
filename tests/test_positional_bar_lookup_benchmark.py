import json
from pathlib import Path
from backtest.benchmark_legacy_run import benchmark


def test_bar_lookup_profile_is_opt_in_and_compares_trade_reports(monkeypatch, tmp_path):
    commands=[]
    def fake_run(argv,check):
        assert check
        commands.append(list(argv))
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
            "result":{"trades":[{"pnl_usd":1.3}],"results":[]},
            "elapsed_seconds":2.0,"peak_process_rss_kib":1000,
        }))
    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run",fake_run)
    value=benchmark(tmp_path,"2026-09-01","2026-09-08",
                    tmp_path/"output",include_bar_lookup_profile=True)
    assert value["parity_passed"]
    assert list(value["measurements"])==["MEMORY","SQLITE","MEMORY_BAR_LOOKUP"]
    assert all("--positional-bar-lookup" not in x for x in commands[:2])
    assert "--positional-bar-lookup" in commands[2]
    assert commands[2][commands[2].index("--quote-csv-parser")+1] == "DICT"
    assert value["measurements"]["MEMORY_BAR_LOOKUP"]["positional_bar_lookup"]
