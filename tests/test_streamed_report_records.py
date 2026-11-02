"""Exact legacy trade/fee/decision output with incremental aggregate records."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtest import ema_vwap_research as research
from backtest.streamed_report_records import StreamedReportRecords


def _mock_market(monkeypatch):
    ns = research.run_dataset.__globals__
    monkeypatch.setitem(ns, "indicators", lambda path: object())
    monkeypatch.setitem(ns, "_option_specs", lambda path: [])

    def signals(*args, **kwargs):
        group = "MACD" if kwargs["require_macd"] else "BASE"
        kwargs["signal_diagnostics"]["signals"] = 2
        if kwargs["decision_events"] is not None:
            kwargs["decision_events"].append({
                "stage": "SIGNAL", "reason": group,
            })
        return [
            SimpleNamespace(
                timestamp_ns=research.timestamp_ns(
                    f"2026-11-01T00:0{i}:00Z"
                ),
                option=SimpleNamespace(symbol=f"{group}-{i}"),
                direction="CALL", entry_type="BASELINE",
                ema_regime_start_ns=0, quotes=[], execution_attempt=None,
            )
            for i in (2, 4)
        ]

    def capture(path, events, **kwargs):
        for event in events:
            event.quotes = [{"bid": 1.0, "ask": 2.0}] * 20

    def simulate(event, frame, scenario, **kwargs):
        event.execution_attempt = {
            "symbol": event.option.symbol, "quantity": 5,
        }
        return {
            "scenario": scenario.name, "symbol": event.option.symbol,
            "exit_time": (
                "2026-11-01T00:03:00+00:00"
                if event.option.symbol.endswith("-2")
                else "2026-11-01T00:05:00+00:00"
            ),
            "exit_reason": "MAX_HOLD",
            "fees_usd": 0.02, "pnl_usd": 0.3,
        }, None

    monkeypatch.setitem(ns, "signal_events", signals)
    monkeypatch.setitem(ns, "capture_quotes", capture)
    monkeypatch.setitem(ns, "simulate_trade", simulate)


@pytest.mark.parametrize("retain_decisions", [True, False])
@pytest.mark.parametrize("release_config", [True, False])
def test_streamed_run_preserves_whole_report_and_cleans_spool(
    monkeypatch, tmp_path, retain_decisions, release_config,
):
    _mock_market(monkeypatch)
    scenarios = [
        research.Scenario("base-1", 1, "EMA"),
        research.Scenario("macd-1", 1, "EMA", require_macd=True),
        research.Scenario("base-2", 1, "EMA_VWAP"),
        research.Scenario("macd-2", 1, "EMA_VWAP", require_macd=True),
    ]
    args = dict(
        start="2026-11-01T00:00:00Z",
        end="2026-11-02T00:00:00Z",
        scenario_set=scenarios,
        quote_csv_parser="DICT",
        retain_decision_events=retain_decisions,
        release_completed_configurations=release_config,
    )
    baseline = research.run_dataset(tmp_path, **args)
    destination = tmp_path / "report.json"
    result = research.run_dataset_to_streamed_report(
        tmp_path, output=destination,
        spool_directory=tmp_path / "spool", **args,
    )
    # Python dataclass settings can contain tuples; compare serialized
    # report forms because JSON necessarily normalizes those into lists.
    assert json.loads(destination.read_text()) == json.loads(
        json.dumps(baseline, allow_nan=False)
    )
    assert result["report_bytes"] == destination.stat().st_size
    assert result["counts"] == {
        "trades": len(baseline["trades"]),
        "execution_attempts": len(baseline["execution_attempts"]),
        "decision_events": len(baseline["decision_events"]),
    }
    assert len(baseline["trades"]) == 8
    assert len(baseline["execution_attempts"]) == 8
    assert not list((tmp_path / "spool").iterdir())


def test_jsonl_spool_order_counts_and_atomic_write(tmp_path):
    report_file = tmp_path / "summary.json"
    with StreamedReportRecords(spool_directory=tmp_path / "spool") as spool:
        trades = spool.sink("trades")
        trades.extend([{"pnl_usd": i * 0.1} for i in range(1500)])
        attempts = spool.sink("execution_attempts")
        attempts.append({"symbol": "BTC-CE"})
        decisions = spool.sink("decision_events")
        decisions.append({"reason": "TRADE_ACCEPTED"})
        report = {
            "settings": {"fees": {"gst_rate": 0.18}},
            "results": [{"scenario": {"name": "H6"}}],
            "trades": trades,
            "execution_attempts": attempts,
            "decision_events": decisions,
        }
        result = spool.write_report(report, report_file)
        assert result["counts"]["trades"] == 1500
        parsed = json.loads(report_file.read_text())
        assert parsed["trades"] == [{"pnl_usd": i * 0.1} for i in range(1500)]
        assert parsed["decision_events"] == [{"reason": "TRADE_ACCEPTED"}]
    assert not list((tmp_path / "spool").iterdir())
    assert not list(tmp_path.glob("*.partial"))


def test_streamed_output_failure_preserves_existing_report(tmp_path, monkeypatch):
    report_file = tmp_path / "existing.json"
    report_file.write_text('{"old":true}', encoding="utf-8")
    with StreamedReportRecords(spool_directory=tmp_path / "spool") as spool:
        report = {"trades": spool.sink("trades")}
        report["trades"].append({"pnl_usd": 3.0})
        def cannot_replace(*args, **kwargs):
            raise OSError("disk write unavailable")
        monkeypatch.setattr("backtest.streamed_report_records.os.replace",
                            cannot_replace)
        with pytest.raises(OSError, match="disk write unavailable"):
            spool.write_report(report, report_file)
        assert json.loads(report_file.read_text()) == {"old": True}
        assert not list(tmp_path.glob("*.partial"))
    assert not list((tmp_path / "spool").iterdir())


def test_streamed_spool_rejects_wrong_field_and_invalid_numbers(tmp_path):
    with StreamedReportRecords() as spool:
        with pytest.raises(ValueError, match="REPORT_SPOOL_FIELD_MISMATCH"):
            spool.write_report({"trades": []}, tmp_path / "bad.json")
        with pytest.raises(ValueError):
            spool.sink("trades").append({"pnl_usd": float("nan")})
        assert len(spool.sink("trades")) == 0
    assert not (tmp_path / "bad.json").exists()
