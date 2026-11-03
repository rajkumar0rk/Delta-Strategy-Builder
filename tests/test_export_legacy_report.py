"""End-to-end file-export parity for legacy H6 streamed records."""
import csv
import json
from pathlib import Path

import pytest

from backtest import ema_vwap_research as legacy
from backtest.export_legacy_report import export_legacy_report
from backtest.streamed_report_records import StreamedReportRecords


def _sample_report():
    return {
        "data_directory": "historical",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-15T00:00:00Z",
        "raw_signals_with_contract": 2,
        "settings": {"timeframe": "5m", "session": (0, 16)},
        "results": [{"scenario": {"name": "H6"}, "metrics": {"trades": 2}}],
        "trades": [
            {"scenario": "H6", "fees_usd": 0.03, "pnl_usd": 0.5},
            {"scenario": "H6", "fees_usd": 0.06, "pnl_usd": -0.2},
        ],
        "execution_attempts": [
            {"symbol": "CE", "quantity": 5, "trade_accepted": True},
            {"symbol": "PE", "quantity": 5, "rejection_reason": "SPREAD"},
        ],
        "decision_events": [
            {"reason": "ENTER", "stage": "SIGNAL", "scenario": "H6"},
            {"reason": "SPREAD", "stage": "EXECUTION", "symbol": "PE"},
        ],
    }


def _fake_dataset(directory, *, report_record_spool=None, **kwargs):
    report = _sample_report()
    if report_record_spool is not None:
        for field in ("trades", "execution_attempts", "decision_events"):
            sink = report_record_spool.sink(field)
            sink.extend(report[field])
            report[field] = sink
    return report


def test_streamed_cli_exports_original_json_and_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(legacy, "run_dataset", _fake_dataset)
    # Some legacy tests reload the research module; patch the exact global
    # namespace held by the already imported streamed-output helper too.
    monkeypatch.setitem(
        legacy.run_dataset_to_streamed_report.__globals__,
        "run_dataset", _fake_dataset,
    )
    monkeypatch.setattr(legacy, "locked_h6_scenarios", lambda: [])
    old_dir = tmp_path / "old"
    stream_dir = tmp_path / "stream"
    memory = export_legacy_report(
        tmp_path, start="2026-09-01T00:00:00Z",
        end="2026-09-15T00:00:00Z", output=old_dir, storage="MEMORY",
    )
    streaming = export_legacy_report(
        tmp_path, start="2026-09-01T00:00:00Z",
        end="2026-09-15T00:00:00Z", output=stream_dir,
        spool_directory=tmp_path / "scratch",
    )
    assert streaming["storage"] == "STREAMED"
    assert streaming["quote_storage"] == "PACKED_MEMORY"
    assert memory["storage"] == "MEMORY"
    assert memory["quote_storage"] == "MEMORY"
    assert streaming["counts"] == memory["counts"] == {
        "trades": 2, "execution_attempts": 2, "decision_events": 2,
    }
    assert json.loads((old_dir / "summary.json").read_text()) == json.loads(
        (stream_dir / "summary.json").read_text()
    )
    for field in ("trades", "execution_attempts", "decision_events"):
        assert (stream_dir / f"{field}.csv").read_bytes() == (
            old_dir / f"{field}.csv"
        ).read_bytes()
    assert not list((tmp_path / "scratch").iterdir())


def test_streamed_csv_preserves_existing_file_on_failed_row(tmp_path):
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    old = report_dir / "trades.csv"
    old.write_text("original", encoding="utf-8")
    with StreamedReportRecords() as spool:
        sink = spool.sink("trades")
        sink.append({"symbol": "A", "pnl_usd": 1})
        sink.append({"symbol": "B", "pnl_usd": 2, "unexpected": "EXTRA"})
        with pytest.raises(ValueError):
            spool.write_csv_exports(report_dir)
    assert old.read_text() == "original"
    assert not list(report_dir.glob("*.partial"))


def test_streamed_csv_omits_empty_fields_and_keeps_first_seen_headers(tmp_path):
    with StreamedReportRecords() as spool:
        spool.sink("execution_attempts").extend([
            {"symbol": "A", "quantity": 5},
            {"quantity": 3, "reason": "NO_LIQUIDITY"},
        ])
        paths = spool.write_csv_exports(tmp_path)
        assert set(paths) == {"execution_attempts"}
    with (tmp_path / "execution_attempts.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["symbol", "quantity", "reason"]
        assert [row["reason"] for row in reader] == ["", "NO_LIQUIDITY"]


def test_file_export_rejects_incompatible_spool_configuration(tmp_path):
    with pytest.raises(ValueError, match="spool_directory"):
        export_legacy_report(
            tmp_path, start="a", end="b", output=tmp_path / "out",
            storage="MEMORY", spool_directory=tmp_path,
        )
    with pytest.raises(ValueError, match="storage"):
        export_legacy_report(
            tmp_path, start="a", end="b", output=tmp_path / "out",
            storage="INVALID",
        )


def test_streamed_export_forwards_default_packed_and_explicit_dictionary_rollback(
    monkeypatch, tmp_path,
):
    selected_modes = []

    def fake_streamed(*args, **kwargs):
        selected_modes.append(kwargs["quote_capture_storage"])
        return {
            "report_path": str(kwargs["output"]),
            "csv_paths": {},
            "counts": {
                "trades": 0, "execution_attempts": 0, "decision_events": 0,
            },
        }

    monkeypatch.setattr(legacy, "run_dataset_to_streamed_report", fake_streamed)
    monkeypatch.setattr(legacy, "locked_h6_scenarios", lambda: [])
    args = dict(
        start="2026-09-01T00:00:00Z",
        end="2026-09-15T00:00:00Z",
        output=tmp_path / "report",
    )
    default = export_legacy_report(tmp_path, **args)
    fallback = export_legacy_report(
        tmp_path, **args, quote_storage="MEMORY",
    )
    explicit = export_legacy_report(
        tmp_path, **args, quote_storage="PACKED_MEMORY",
    )
    assert selected_modes == ["PACKED_MEMORY", "MEMORY", "PACKED_MEMORY"]
    assert [v["quote_storage"] for v in (default, fallback, explicit)] == selected_modes


@pytest.mark.parametrize("bad", ["SQLITE", "UNKNOWN", ""])
def test_file_export_rejects_invalid_quote_storage_before_running(tmp_path, bad):
    with pytest.raises(ValueError, match="quote_storage"):
        export_legacy_report(
            tmp_path, start="a", end="b", output=tmp_path / "out",
            quote_storage=bad,
        )


def test_original_memory_export_rejects_packed_override(tmp_path):
    with pytest.raises(ValueError, match="requires STREAMED"):
        export_legacy_report(
            tmp_path, start="a", end="b", output=tmp_path / "out",
            storage="MEMORY", quote_storage="PACKED_MEMORY",
        )


def test_default_research_runner_quote_storage_unchanged():
    from inspect import signature
    assert signature(legacy.run_dataset).parameters[
        "quote_capture_storage"
    ].default == "MEMORY"
