"""Default parser promotion must preserve the legacy fallback and benchmark oracle."""
import inspect
from pathlib import Path

from backtest import ema_vwap_research as research
from backtest.benchmark_legacy_run import benchmark


def test_legacy_default_is_positional_and_explicit_dict_is_supported():
    signature = inspect.signature(research.run_dataset)
    assert signature.parameters["quote_csv_parser"].default == "POSITIONAL"


def test_legacy_benchmark_baselines_explicitly_pin_dict(monkeypatch, tmp_path):
    import json
    calls = []

    def fake_run(argv, check):
        assert check is True
        calls.append(list(argv))
        path = Path(argv[argv.index("--output") + 1])
        path.write_text(json.dumps({
            "result": {"trades": [{"pnl_usd": 1.0}], "results": []},
            "elapsed_seconds": 1.0,
            "peak_process_rss_kib": 1000,
        }))
    monkeypatch.setattr("backtest.benchmark_legacy_run.subprocess.run", fake_run)
    report = benchmark(tmp_path, "2026-09-01", "2026-09-08",
                       tmp_path / "report", include_positional_profile=True)
    assert report["parity_passed"]
    assert len(calls) == 3
    parsers = [args[args.index("--quote-csv-parser") + 1] for args in calls]
    assert parsers == ["DICT", "DICT", "POSITIONAL"]


def test_legacy_candle_lookup_default_enabled_with_explicit_opt_out():
    signature = inspect.signature(research.run_dataset)
    assert signature.parameters["positional_bar_lookup"].default is True
    assert signature.parameters["positional_bar_lookup"].kind is inspect.Parameter.KEYWORD_ONLY
