import json
from pathlib import Path

from backtest.benchmark_positional_ab import benchmark_positional_ab


def test_balanced_frame_trim_compares_identical_parser_and_candle_lookup(monkeypatch, tmp_path):
    order=[]
    def run(argv,check):
        assert check is True
        assert argv[argv.index("--mode")+1]=="MEMORY"
        assert argv[argv.index("--algorithm")+1]=="LEGACY"
        assert argv[argv.index("--quote-csv-parser")+1]=="POSITIONAL"
        assert "--positional-bar-lookup" in argv
        reduced="--trim-simulation-frame" in argv
        order.append(reduced)
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
            "result": {
                "trades":[{"fees_usd":0.03,"pnl_usd":2.0}],
                "execution_attempts":[{"quantity":5}],
                "decision_events":[{"status":"ACCEPTED"}],
            },
            "elapsed_seconds": 10.0 if not reduced else 8.0,
            "peak_process_rss_kib": 102400 if not reduced else 100000,
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run",run)
    result=benchmark_positional_ab(
        tmp_path,"2026-09-01","2026-09-15",tmp_path/"report",
        comparison="FRAME_TRIM",rounds=2,
    )
    assert order == [False,True,True,False,True,False,False,True]
    assert result["parity_passed"]
    assert result["difference_count"]==0
    assert result["baseline_variant"]=="POSITIONAL_BAR_LOOKUP"
    assert result["candidate_variant"]=="POSITIONAL_FRAME_TRIM"
    assert result["median_time_reduction_percent"]==20.0
    assert result["measurements"][1]["trim_simulation_frame"]
    assert not result["measurements"][0]["trim_simulation_frame"]
