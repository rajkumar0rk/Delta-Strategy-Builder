"""Exact legacy report parity with packed memory quote capture and balanced AB."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtest import ema_vwap_research as research
from backtest.benchmark_report_streaming import benchmark_streamed_reports


def test_packed_memory_and_original_quotes_produce_identical_reports(monkeypatch, tmp_path):
    runner = research.run_dataset
    ns = runner.__globals__
    monkeypatch.setitem(ns, "indicators", lambda path: object())
    monkeypatch.setitem(ns, "_option_specs", lambda path: [])

    def signals(*args, **kwargs):
        if kwargs["decision_events"] is not None:
            kwargs["decision_events"].append({
                "stage": "SIGNAL", "reason": "MATCH",
            })
        return [
            SimpleNamespace(
                timestamp_ns=research.timestamp_ns("2026-09-01T00:00:00Z"),
                option=SimpleNamespace(symbol="BTC-CE"),
                direction="CALL", entry_type="BASELINE",
                ema_regime_start_ns=0, quotes=[], execution_attempt=None,
            )
        ]

    def capture(path, events, *, quote_store=None, **kwargs):
        for event in events:
            quotes = [
                {"timestamp_ns": float(i), "bid": 1.25 + i,
                 "ask": 1.45 + i, "bid_size": 5.0,
                 "ask_size": 5.0, "volume": 50.0, "open_interest": 10.0}
                for i in range(1, 6)
            ]
            if quote_store is None:
                event.quotes = quotes
            else:
                event.quotes = quote_store.view(id(event))
                for quote in quotes:
                    quote_store.append(id(event), quote)
        if quote_store is not None:
            quote_store.flush()

    def simulate(event, frame, scenario, **kwargs):
        assert event.quotes[0]["bid"] == 2.25
        assert event.quotes[-1]["ask"] == 6.45
        assert len(list(reversed(event.quotes))) == 5
        event.execution_attempt = {
            "symbol": event.option.symbol, "quantity": 5,
        }
        return {
            "scenario": scenario.name,
            "symbol": event.option.symbol,
            "exit_time": "2026-09-01T00:05:00+00:00",
            "exit_reason": "MAX_HOLD",
            "fees_usd": 0.02, "pnl_usd": 0.4,
        }, None

    monkeypatch.setitem(ns, "signal_events", signals)
    monkeypatch.setitem(ns, "capture_quotes", capture)
    monkeypatch.setitem(ns, "simulate_trade", simulate)
    kwargs = dict(
        start="2026-09-01T00:00:00Z", end="2026-09-02T00:00:00Z",
        quote_csv_parser="DICT",
        scenario_set=[research.Scenario("original", 1, "EMA")],
    )
    original = runner(tmp_path, **kwargs)
    packed = runner(tmp_path, quote_capture_storage="PACKED_MEMORY", **kwargs)
    assert json.loads(json.dumps(packed)) == json.loads(json.dumps(original))
    assert len(original["trades"]) == 1
    assert len(packed["execution_attempts"]) == 1
    assert len(packed["decision_events"]) >= 2


def test_balanced_quote_storage_benchmark_pins_streamed_reports(monkeypatch, tmp_path):
    order = []

    def run(argv, check):
        assert check
        mode = argv[argv.index("--mode")+1]
        order.append(mode)
        assert mode in {"STREAMED", "STREAMED_PACKED_QUOTES"}
        output = Path(argv[argv.index("--output")+1])
        report = {
            "trades": [{"fees_usd": 0.02, "pnl_usd": 1.2}],
            "execution_attempts": [{"quantity": 5}],
            "decision_events": [{"reason": "ENTER"}],
        }
        output.write_text(json.dumps(report), encoding="utf-8")
        metrics = Path(argv[argv.index("--metadata")+1])
        metrics.write_text(json.dumps({
            "mode": mode,
            "elapsed_seconds": 9 if mode=="STREAMED" else 8,
            "peak_process_rss_kib": 90000 if mode=="STREAMED" else 85000,
            "report_bytes": output.stat().st_size,
            "counts": {"trades":1, "execution_attempts":1, "decision_events":1},
        }), encoding="utf-8")

    monkeypatch.setattr("backtest.benchmark_report_streaming.subprocess.run", run)
    result = benchmark_streamed_reports(
        tmp_path, "2026-09-01", "2026-09-15",
        tmp_path/"report", comparison="QUOTE_STORAGE", rounds=2,
    )
    assert order == [
        "STREAMED", "STREAMED_PACKED_QUOTES",
        "STREAMED_PACKED_QUOTES", "STREAMED",
        "STREAMED_PACKED_QUOTES", "STREAMED",
        "STREAMED", "STREAMED_PACKED_QUOTES",
    ]
    assert result["parity_passed"]
    assert result["difference_count"] == 0
    assert result["baseline_mode"] == "STREAMED"
    assert result["candidate_mode"] == "STREAMED_PACKED_QUOTES"
    assert result["statistics"]["STREAMED"]["median_peak_rss_kib"] == 90000
    assert result["statistics"]["STREAMED_PACKED_QUOTES"]["median_peak_rss_kib"] == 85000


def test_invalid_quote_storage_comparison_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="comparison"):
        benchmark_streamed_reports(
            tmp_path, "2026-09-01", "2026-09-15",
            tmp_path/"out", comparison="INVALID",
        )
