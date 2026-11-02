"""Minimal streaming CSV primitives shared by legacy offline research readers.

Every row is read lazily. Callers may still materialize a selected result, but
never allocate a second full-file list before filtering timestamps.
No dependency on Strategy Lab or historical archive layout.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator


def iter_csv_rows(path: str | Path) -> Iterator[dict[str, str]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"required historical data file not found: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def selected_rows(
    path: str | Path, *, start_ns: int, end_ns: int,
    timestamp_ns, limit: int | None = None,
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield filtered row once; fail closed before exceeding configured record cap."""
    if end_ns <= start_ns:
        raise ValueError("end must follow start")
    if limit is not None and limit < 1:
        raise ValueError("selected-row limit must be positive")
    count = 0
    for row in iter_csv_rows(path):
        stamp = timestamp_ns(row["timestamp"])
        if start_ns <= stamp < end_ns:
            count += 1
            if limit is not None and count > limit:
                raise ValueError(
                    f"BACKTEST_RECORD_LIMIT_EXCEEDED: {Path(path).name} has more "
                    f"than {limit} selected rows"
                )
            yield stamp, row
