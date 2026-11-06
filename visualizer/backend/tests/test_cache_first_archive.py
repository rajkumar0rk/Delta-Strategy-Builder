"""Archive market routing and physical candle sync orchestration."""
from __future__ import annotations

import csv
import json

from app import archive_sync
from app.models import ArchiveSyncRequest


def _catalog(tmp_path, *, option_files: bool = False):
    root = tmp_path / "data"
    dest = root / "segments" / "fixture"
    dest.mkdir(parents=True)
    (root / "catalog.json").write_text(json.dumps({
        "format_version": 1,
        "segments": [{
            "name": "fixture",
            "directory": "segments/fixture",
            "start": "2026-01-01T00:00:00Z",
            "end_exclusive": "2026-01-01T00:15:00Z",
        }],
    }), encoding="utf-8")
    with (dest / "underlying_bars.csv").open("w", newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=[
            "timestamp","open","high","low","close","volume"])
        writer.writeheader()
        writer.writerow(dict(timestamp="2026-01-01T00:00:00Z",
                             open=100,high=101,low=99,close=100,volume=1))
    if option_files:
        for name in ("option_instruments.csv", "option_quotes.csv"):
            (dest / name).write_text("timestamp\n", encoding="utf-8")
    return root


def test_futures_plan_ignores_option_files_but_options_plan_requires_them(tmp_path):
    root=_catalog(tmp_path)
    futures=archive_sync.plan_archive_sync(
        "2026-01-01T00:00:00Z","2026-01-01T00:15:00Z",
        root=root,require_options=False)
    options=archive_sync.plan_archive_sync(
        "2026-01-01T00:00:00Z","2026-01-01T00:15:00Z",
        root=root,require_options=True)
    assert futures["ready"] is True
    assert options["ready"] is False
    assert options["missing_segment_files"][0]["missing"] == [
        "option_instruments.csv", "option_quotes.csv"]


def test_options_and_futures_cache_check_run_even_when_catalog_is_complete(
    tmp_path, monkeypatch,
):
    root=_catalog(tmp_path,option_files=True)
    monkeypatch.setattr(archive_sync,"data_root",lambda:root)
    calls=[]
    def inspect(target,start,end,progress=None,*,append_catalog_gaps=False):
        calls.append((target,start,end,append_catalog_gaps))
    monkeypatch.setattr(archive_sync,"_run_btc_candle_gap_repair",inspect)
    for market in (False,True):
        result=archive_sync.ensure_archive_data(
            "2026-01-01T00:00:00Z","2026-01-01T00:15:00Z",
            require_options=market)
        assert result["plan_after"]["ready"]
    assert len(calls)==2
    assert all(item[3] is False for item in calls)


def test_futures_uncatalogued_range_uses_btc_only_append_path(
    tmp_path, monkeypatch,
):
    root=_catalog(tmp_path)
    monkeypatch.setattr(archive_sync,"data_root",lambda:root)
    calls=[]
    def inspect(target,start,end,progress=None,*,append_catalog_gaps=False):
        calls.append(append_catalog_gaps)
        if append_catalog_gaps:
            # Simulate subprocess updating the canonical catalog with the new range.
            payload=json.loads((root/"catalog.json").read_text())
            payload["segments"].append({
                "name":"new","directory":"segments/new",
                "start":"2026-01-01T00:15:00Z",
                "end_exclusive":"2026-01-01T00:30:00Z",
            })
            target_file=root/"segments"/"new"/"underlying_bars.csv"
            target_file.parent.mkdir(parents=True)
            target_file.write_text("timestamp,open,high,low,close,volume\n")
            (root/"catalog.json").write_text(json.dumps(payload))
    monkeypatch.setattr(archive_sync,"_run_btc_candle_gap_repair",inspect)
    monkeypatch.setattr(archive_sync,"_run_sync_range",
                        lambda *a,**k: (_ for _ in ()).throw(
                            AssertionError("Futures must never download option quote datasets")))
    result=archive_sync.ensure_archive_data(
        "2026-01-01T00:00:00Z","2026-01-01T00:30:00Z",
        require_options=False)
    assert result["plan_after"]["ready"]
    assert calls==[True,False]


def test_archive_request_market_is_separate_from_strategy():
    assert ArchiveSyncRequest(start="2026-01-01T00:00:00Z",
                              end="2026-01-01T00:05:00Z").market_type=="OPTIONS"
    request=ArchiveSyncRequest(start="2026-01-01T00:00:00Z",
                               end="2026-01-01T00:05:00Z",
                               market_type="FUTURES")
    assert request.market_type=="FUTURES"
