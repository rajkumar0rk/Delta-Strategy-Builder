import json
from pathlib import Path
import pytest
from backtest.benchmark_positional_ab import benchmark_positional_ab


def test_balanced_bar_lookup_comparison_and_full_report_parity(monkeypatch,tmp_path):
    calls=[]
    def fake_run(argv,check):
        assert check
        parser=argv[argv.index("--quote-csv-parser")+1]
        assert parser=="POSITIONAL"
        lookup="--positional-bar-lookup" in argv
        calls.append(lookup)
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
          "result":{"trades":[{"pnl_usd":5}],"execution_attempts":[{}]},
          "elapsed_seconds":5.0 if lookup else 10.0,
          "peak_process_rss_kib":1000,
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run",fake_run)
    result=benchmark_positional_ab(tmp_path,"2026-09-01","2026-09-08",
             tmp_path/"report",rounds=2,comparison="BAR_LOOKUP")
    assert calls==[False,True,True,False,True,False,False,True]
    assert result["parity_passed"]
    assert result["baseline_trade_count"]==1
    assert result["baseline_variant"]=="POSITIONAL"
    assert result["candidate_variant"]=="POSITIONAL_BAR_LOOKUP"
    assert result["median_time_reduction_percent"]==pytest.approx(50)
    assert result["statistics"]["POSITIONAL"]["runs"]==4
    assert result["statistics"]["POSITIONAL_BAR_LOOKUP"]["runs"]==4


def test_existing_output_does_not_reuse_stale_baseline(monkeypatch,tmp_path):
    directory=tmp_path/"report"
    directory.mkdir()
    (directory/"reference-positional-report.json").write_text(
      json.dumps({"trades":[{"pnl_usd":999}]}))
    def fake_run(argv,check):
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
          "result":{"trades":[{"pnl_usd":1}],"execution_attempts":[]},
          "elapsed_seconds":1.0,
          "peak_process_rss_kib":1000,
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run",fake_run)
    result=benchmark_positional_ab(tmp_path,"2026-09-01","2026-09-08",
                directory,rounds=1,comparison="BAR_LOOKUP")
    assert result["parity_passed"]
    assert json.loads((directory/"reference-positional-report.json").read_text())["trades"][0]["pnl_usd"]==1


def test_bad_comparison_rejected(tmp_path):
    with pytest.raises(ValueError,match="comparison"):
        benchmark_positional_ab(tmp_path,"a","b",tmp_path/"report",comparison="BAD")
