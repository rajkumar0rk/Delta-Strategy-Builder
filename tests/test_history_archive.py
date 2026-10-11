import json
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from backtest.history_archive import (
    ArchiveSegment,
    load_catalog,
    sync_segment,
    write_catalog,
)


@pytest.fixture
def archive_directory():
    directory = Path(__file__).parent / "testdata" / f"archive-{uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def test_catalog_round_trip(archive_directory: Path):
    segments = (
        ArchiveSegment(
            "2026-01",
            archive_directory / "segments" / "2026-01",
            "2026-01-01T00:00:00Z",
            "2026-02-01T00:00:00Z",
        ),
        ArchiveSegment(
            "2026-02",
            archive_directory / "segments" / "2026-02",
            "2026-02-01T00:00:00Z",
            "2026-03-01T00:00:00Z",
        ),
    )

    path = write_catalog(archive_directory, segments)

    assert path == archive_directory / "catalog.json"
    assert load_catalog(archive_directory) == segments
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["segments"][0]["directory"] == "segments/2026-01"


def test_sync_rejects_incomplete_future_date(archive_directory: Path):
    with pytest.raises(ValueError, match="completed UTC date"):
        sync_segment(
            archive_directory,
            date(2999, 1, 1),
            date(2999, 1, 2),
        )
