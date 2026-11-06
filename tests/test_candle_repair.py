"""Cache-first Delta BTC 5m history repair: no network unless timestamps are missing."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest.candle_repair import (
    append_btc_catalog_gaps, missing_candles, repair_missing_btc_candles,
)

START = "2026-01-01T00:00:00Z"
END = "2026-01-01T00:15:00Z"
NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, drop=None):
        self.calls = []
        self.drop = set(drop or [])

    def candles(self, symbol, start, end, resolution="5m"):
        assert (symbol, resolution) == ("BTCUSD", "5m")
        self.calls.append((start, end))
        return [
            dict(time=t, open=100.0, high=101.0, low=99.0, close=100.0, volume=3.0)
            for t in range(start, end, 300) if t not in self.drop
        ]


def _archive(root: Path, *, timestamps=(START, "2026-01-01T00:05:00Z",
                                        "2026-01-01T00:10:00Z"),
             segment_end=END):
    directory = root / "segments" / "existing"
    directory.mkdir(parents=True)
    (root / "catalog.json").write_text(json.dumps({
        "format_version": 1,
        "segments": [{
            "name": "existing", "directory": "segments/existing",
            "start": START, "end_exclusive": segment_end,
        }],
    }), encoding="utf-8")
    path = directory / "underlying_bars.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "timestamp", "open", "high", "low", "close", "volume"
        ])
        writer.writeheader()
        for when in timestamps:
            writer.writerow(dict(timestamp=when, open=100, high=101,
                                 low=99, close=100, volume=3))
    return path


def test_reuses_all_cached_candles_without_a_single_api_call(tmp_path):
    path = _archive(tmp_path)
    before = path.read_bytes()
    provider = FakeClient()
    result = repair_missing_btc_candles(tmp_path, START, END, client=provider, now=NOW)
    assert result == {"downloaded": 0, "api_requests": 0, "reused": True}
    assert provider.calls == []
    assert path.read_bytes() == before


def test_backfills_only_one_missing_five_minute_candle(tmp_path):
    path = _archive(tmp_path, timestamps=(START, "2026-01-01T00:10:00Z"))
    before = path.read_text()
    provider = FakeClient()
    result = repair_missing_btc_candles(tmp_path, START, END, client=provider, now=NOW)
    assert result["downloaded"] == 1
    assert provider.calls == [(1767225600, 1767225900)]
    assert missing_candles(tmp_path, START, END) == []
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["timestamp"] for r in rows] == [
        START, "2026-01-01T00:05:00Z", "2026-01-01T00:10:00Z"
    ]
    assert rows[0]["open"] == "100"
    assert before != path.read_text()
    provider2 = FakeClient()
    assert repair_missing_btc_candles(tmp_path, START, END, client=provider2, now=NOW)["reused"]
    assert provider2.calls == []


def test_incomplete_remote_response_preserves_existing_csv_exactly(tmp_path):
    path = _archive(tmp_path, timestamps=(START,))
    original = path.read_bytes()
    original_catalog = (tmp_path / "catalog.json").read_bytes()
    missing_first_open = 1767225600
    provider = FakeClient(drop={missing_first_open})
    with pytest.raises(RuntimeError, match="BTC_CANDLE_DOWNLOAD_INCOMPLETE"):
        repair_missing_btc_candles(tmp_path, START, END, client=provider, now=NOW)
    assert path.read_bytes() == original
    assert (tmp_path / "catalog.json").read_bytes() == original_catalog


def test_only_new_catalog_gap_is_downloaded_using_btc_candles(tmp_path):
    path = _archive(tmp_path, timestamps=(START, "2026-01-01T00:05:00Z"),
                    segment_end="2026-01-01T00:10:00Z")
    before = path.read_bytes()
    client = FakeClient()
    result = append_btc_catalog_gaps(tmp_path, START, END, client=client, now=NOW)
    assert result["appended_segments"] == 1
    assert result["downloaded"] == 1
    assert len(client.calls) == 1
    assert path.read_bytes() == before
    assert missing_candles(tmp_path, START, END) == []
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert len(catalog["segments"]) == 2
    assert catalog["segments"][1]["directory"].startswith("segments/btc-only-")
    again = FakeClient()
    assert append_btc_catalog_gaps(tmp_path, START, END, client=again, now=NOW)["downloaded"] == 0
    assert again.calls == []


def test_new_archive_bootstraps_only_requested_btc_candles(tmp_path):
    client = FakeClient()
    result = append_btc_catalog_gaps(tmp_path, START, END, client=client, now=NOW)
    assert result["downloaded"] == 3
    assert result["appended_segments"] == 1
    assert missing_candles(tmp_path, START, END) == []
    assert len(client.calls) == 1


def test_failed_catalog_gap_download_does_not_publish_partial_history(tmp_path):
    client = FakeClient(drop={1767225300})
    with pytest.raises(RuntimeError, match="BTC_CANDLE_DOWNLOAD_INCOMPLETE"):
        append_btc_catalog_gaps(tmp_path, START, END, client=client, now=NOW)
    assert not (tmp_path / "catalog.json").exists()


def test_does_not_download_future_unclosed_five_minute_candles(tmp_path):
    _archive(tmp_path, timestamps=(START,))
    with pytest.raises(ValueError, match="BTC_CANDLE_NOT_COMPLETE"):
        repair_missing_btc_candles(tmp_path, START, END, client=FakeClient(),
                                   now=datetime(2026, 1, 1, 0, 6, tzinfo=timezone.utc))


def test_rejects_bad_candles_without_overwriting_existing_csv(tmp_path):
    path = _archive(tmp_path, timestamps=(START, "2026-01-01T00:10:00Z"))
    original = path.read_bytes()

    class BadClient(FakeClient):
        def candles(self, symbol, start, end, resolution="5m"):
            rows = super().candles(symbol, start, end, resolution)
            for row in rows:
                row["low"] = 200  # cannot exceed the candle's close
            return rows

    with pytest.raises(ValueError, match="invalid BTCUSD OHLCV"):
        repair_missing_btc_candles(tmp_path, START, END, client=BadClient(), now=NOW)
    assert path.read_bytes() == original
