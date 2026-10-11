import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.archive_sync import plan_archive_sync
from app.engine import _session_allowed
from app.models import BacktestRequest, SessionConfig, StrategyConfig

UTC = timezone.utc


def test_v13_single_session_migrates_to_window():
    cfg = SessionConfig.model_validate({"timezone": "Asia/Kolkata", "start": "01:00", "end": "06:00", "blocked_weekdays": []})
    assert [(x.start, x.end) for x in cfg.windows] == [("01:00", "06:00")]
    assert cfg.start == "01:00"
    assert cfg.end == "06:00"


def test_multiple_entry_windows_allow_either_and_block_gap():
    cfg = SessionConfig(
        timezone="UTC",
        windows=[{"start": "01:00", "end": "06:00"}, {"start": "10:00", "end": "21:00"}],
    )
    assert _session_allowed(pd.Timestamp("2026-10-08T02:00:00Z"), cfg)
    assert not _session_allowed(pd.Timestamp("2026-10-08T08:00:00Z"), cfg)
    assert _session_allowed(pd.Timestamp("2026-10-08T20:00:00Z"), cfg)


def test_entry_window_can_cross_midnight():
    cfg = SessionConfig(timezone="UTC", windows=[{"start": "22:00", "end": "02:00"}])
    assert _session_allowed(pd.Timestamp("2026-10-08T23:00:00Z"), cfg)
    assert _session_allowed(pd.Timestamp("2026-10-09T01:00:00Z"), cfg)
    assert not _session_allowed(pd.Timestamp("2026-10-09T12:00:00Z"), cfg)


def test_archive_plan_downloads_only_uncovered_completed_days(tmp_path: Path):
    root = tmp_path / "delta-history"
    seg = root / "segments" / "existing"
    seg.mkdir(parents=True)
    for name in ("underlying_bars.csv", "option_instruments.csv", "option_quotes.csv"):
        (seg / name).write_text("header\n", encoding="utf-8")
    (root / "catalog.json").write_text(json.dumps({
        "format_version": 1,
        "segments": [{
            "name": "existing", "directory": "segments/existing",
            "start": "2026-10-01T00:00:00Z", "end_exclusive": "2026-10-04T00:00:00Z",
        }],
    }), encoding="utf-8")

    plan = plan_archive_sync(
        "2026-10-03T00:00:00Z", "2026-10-08T00:00:00Z",
        root=root, now=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    assert plan["download_ranges"] == [{"start_date": "2026-10-04", "end_date": "2026-10-07"}]
    assert plan["unresolved_ranges"] == []
    assert plan["missing_segment_files"] == []


def test_archive_plan_reports_missing_existing_segment_file(tmp_path: Path):
    root = tmp_path / "delta-history"
    seg = root / "segments" / "existing"
    seg.mkdir(parents=True)
    (seg / "underlying_bars.csv").write_text("header\n", encoding="utf-8")
    (root / "catalog.json").write_text(json.dumps({
        "segments": [{
            "name": "existing", "directory": "segments/existing",
            "start": "2026-10-01T00:00:00Z", "end_exclusive": "2026-10-04T00:00:00Z",
        }],
    }), encoding="utf-8")
    plan = plan_archive_sync(
        "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z",
        root=root, now=datetime(2026, 10, 9, tzinfo=UTC),
    )
    assert plan["missing_segment_files"][0]["missing"] == ["option_instruments.csv", "option_quotes.csv"]


def test_backtest_request_accepts_auto_archive_download_flag():
    req = BacktestRequest(
        dataset_mode="ARCHIVE",
        auto_download_missing_data=True,
        start="2026-10-01T00:00:00Z",
        end="2026-10-02T00:00:00Z",
        strategy=StrategyConfig(),
    )
    assert req.auto_download_missing_data is True
