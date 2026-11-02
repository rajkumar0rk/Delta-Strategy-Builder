"""Balanced packed spool benchmark and exact on-disk telemetry tests."""
import json
from pathlib import Path

import pytest

from backtest.benchmark_positional_ab import benchmark_positional_ab
from backtest.event_quote_store import EventQuoteStore


def _quote(n):
    return {
        "timestamp_ns": float(n), "bid": float(n+1), "ask": float(n+2),
        "bid_size": 1.0, "ask_size": 2.0, "volume": 3.0,
        "open_interest": 4.0,
    }


@pytest.mark.parametrize("encoding", ["JSON", "PACKED"])
def test_spool_metrics_real_disk_and_cleanup(tmp_path, encoding):
    spool = EventQuoteStore(directory=tmp_path/"spools", batch_size=3,
                            payload_encoding=encoding)
    try:
        for i in range(8):
            spool.append(10, _quote(i))
        spool.flush()
        stats = spool.snapshot_metrics()
        assert stats["payload_encoding"] == encoding
        assert stats["captured_quote_rows"] == 8
        assert stats["event_count"] == 1
        assert stats["writer_batch_size"] == 3
        assert stats["peak_pending_rows"] == 3
        assert stats["sqlite_disk_bytes"] >= stats["sqlite_pages_bytes"] > 0
        assert list(spool.view(10)) == [_quote(i) for i in range(8)]
    finally:
        spool.close()
    assert not list((tmp_path/"spools").iterdir())
    with pytest.raises(RuntimeError, match="closed"):
        spool.snapshot_metrics()


def test_sqlite_abba_baab_isolates_encoding_and_preserves_full_report(monkeypatch, tmp_path):
    calls = []
    def fake_run(argv, check):
        assert check is True
        parser = argv[argv.index("--quote-csv-parser")+1]
        mode = argv[argv.index("--mode")+1]
        algorithm = argv[argv.index("--algorithm")+1]
        encoding = argv[argv.index("--quote-spool-encoding")+1]
        assert mode == "SQLITE"
        assert algorithm == "SWEEP"
        assert parser == "POSITIONAL"
        assert "--positional-bar-lookup" in argv
        assert "--quote-spool-metrics" in argv
        calls.append(encoding)
        target = Path(argv[argv.index("--output")+1])
        target.write_text(json.dumps({
            "result": {
                "trades": [{"fees_usd": 0.1, "pnl_usd": 2.7}],
                "execution_attempts": [{"size": 5}],
                "decision_events": [{"reason": "TRADE_ACCEPTED"}],
            },
            "elapsed_seconds": 10.0 if encoding=="JSON" else 8.0,
            "peak_process_rss_kib": 90000 if encoding=="JSON" else 88000,
            "quote_spool_metrics": {
                "captured_quote_rows": 120,
                "event_count": 2,
                "sqlite_disk_bytes": 20000 if encoding=="JSON" else 12000,
                "peak_pending_rows": 3,
                "payload_encoding": encoding,
            },
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run", fake_run)
    report = benchmark_positional_ab(
        tmp_path, "2026-09-01", "2026-09-08",
        tmp_path/"out", rounds=2, comparison="SQLITE_ENCODING",
    )
    assert calls == ["JSON","PACKED","PACKED","JSON","PACKED","JSON","JSON","PACKED"]
    assert report["parity_passed"]
    assert report["baseline_trade_count"] == 1
    assert report["median_time_reduction_percent"] == pytest.approx(20.0)
    assert report["statistics"]["SQLITE_JSON"]["median_seconds"] == 10.0
    assert report["statistics"]["SQLITE_PACKED"]["median_seconds"] == 8.0
    assert report["measurements"][1]["quote_spool_metrics"]["sqlite_disk_bytes"] == 12000
    assert report["measurements"][1]["positional_bar_lookup"]
    assert (tmp_path/"out"/"reference-sqlite-json-report.json").exists()


def test_sqlite_ab_fails_when_metrics_missing(monkeypatch, tmp_path):
    def fake_run(argv,check):
        Path(argv[argv.index("--output")+1]).write_text(json.dumps({
            "result": {"trades": []}, "elapsed_seconds": 1.0,
            "peak_process_rss_kib": 3000,
        }))
    monkeypatch.setattr("backtest.benchmark_positional_ab.subprocess.run",fake_run)
    with pytest.raises(ValueError, match="SQLITE_SPOOL_METRICS_MISSING"):
        benchmark_positional_ab(
            tmp_path,"2026-09-01","2026-09-08",
            tmp_path/"out",rounds=1,comparison="SQLITE_ENCODING",
        )
