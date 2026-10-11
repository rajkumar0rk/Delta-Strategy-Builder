from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import data_root, project_root

UTC = timezone.utc


@dataclass(frozen=True)
class SyncRange:
    start_date: date
    end_date: date  # inclusive

    def as_dict(self) -> dict[str, str]:
        return {"start_date": self.start_date.isoformat(), "end_date": self.end_date.isoformat()}


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _day_floor(value: datetime) -> datetime:
    return datetime.combine(value.date(), time.min, tzinfo=UTC)


def _day_ceil(value: datetime) -> datetime:
    floor = _day_floor(value)
    return floor if value == floor else floor + timedelta(days=1)


def _merge_ranges(ranges: list[SyncRange]) -> list[SyncRange]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda x: x.start_date)
    out = [ordered[0]]
    for item in ordered[1:]:
        prev = out[-1]
        if item.start_date <= prev.end_date + timedelta(days=1):
            out[-1] = SyncRange(prev.start_date, max(prev.end_date, item.end_date))
        else:
            out.append(item)
    return out


def plan_archive_sync(start: str, end: str, *, root: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Plan safe downloads for uncovered *completed UTC days*.

    Catalog intervals are authoritative. Existing catalog segments with missing
    normalized files are reported separately because the external archive utility's
    public CLI is designed to append non-overlapping shards, not to silently replace
    a migrated segment that may represent many months.
    """
    root = (root or data_root()).resolve()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    s = _parse(start)
    e = _parse(end)
    if e <= s:
        raise ValueError("Archive sync end must be after start")

    catalog_path = root / "catalog.json"
    catalog: dict[str, Any]
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog = {"segments": []}

    intervals: list[tuple[datetime, datetime, dict[str, Any]]] = []
    missing_files: list[dict[str, Any]] = []
    for raw in catalog.get("segments", []):
        if not isinstance(raw, dict) or not raw.get("start") or not raw.get("end_exclusive"):
            continue
        a = _parse(str(raw["start"]))
        b = _parse(str(raw["end_exclusive"]))
        if b <= s or a >= e:
            continue
        intervals.append((max(s, a), min(e, b), raw))
        seg_root = root / str(raw.get("directory") or "")
        missing = [name for name in ("underlying_bars.csv", "option_instruments.csv", "option_quotes.csv") if not (seg_root / name).is_file()]
        if missing:
            missing_files.append({
                "name": str(raw.get("name") or raw.get("directory") or "segment"),
                "directory": str(raw.get("directory") or ""),
                "start": str(raw["start"]),
                "end_exclusive": str(raw["end_exclusive"]),
                "missing": missing,
            })

    intervals.sort(key=lambda x: x[0])
    gaps: list[tuple[datetime, datetime]] = []
    cursor = s
    for a, b, _ in intervals:
        if a > cursor:
            gaps.append((cursor, a))
        if b > cursor:
            cursor = b
    if cursor < e:
        gaps.append((cursor, e))

    completed_end = _day_floor(now)  # only dates strictly before today's UTC date
    downloadable: list[SyncRange] = []
    unresolved: list[dict[str, str]] = []
    for ga, gb in gaps:
        safe_end = min(gb, completed_end)
        if safe_end > ga:
            # The archive CLI downloads complete UTC dates. Expanding a gap to day
            # boundaries is safe for append-only uncovered intervals and gives the
            # strategy enough warmup/data to cover a partial-day request.
            day_start = _day_floor(ga).date()
            day_end_exclusive = _day_ceil(safe_end)
            if day_end_exclusive > completed_end:
                day_end_exclusive = completed_end
            if day_end_exclusive.date() > day_start:
                downloadable.append(SyncRange(day_start, day_end_exclusive.date() - timedelta(days=1)))
        if gb > completed_end:
            unresolved.append({"start": _iso(max(ga, completed_end)), "end_exclusive": _iso(gb), "reason": "UTC day is not completed yet"})

    downloadable = _merge_ranges(downloadable)
    module_path = project_root() / "backtest" / "history_archive.py"
    return {
        "root": str(root),
        "catalog_path": str(catalog_path),
        "module_path": str(module_path),
        "module_available": module_path.is_file(),
        "requested_start": _iso(s),
        "requested_end": _iso(e),
        "catalog_gaps": [{"start": _iso(a), "end_exclusive": _iso(b)} for a, b in gaps],
        "download_ranges": [x.as_dict() for x in downloadable],
        "unresolved_ranges": unresolved,
        "missing_segment_files": missing_files,
        "needs_download": bool(downloadable),
        "ready": not gaps and not missing_files,
    }


def _run_sync_range(root: Path, item: SyncRange, progress: Callable[..., None] | None = None) -> None:
    cmd = [
        sys.executable,
        "-m",
        "backtest.history_archive",
        "--root",
        str(root),
        "sync",
        "--start-date",
        item.start_date.isoformat(),
        "--end-date",
        item.end_date.isoformat(),
    ]
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            message = raw.strip()
            if message and progress:
                progress(message)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"history_archive sync exited with code {code}")
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise


def ensure_archive_data(start: str, end: str, progress: Callable[..., None] | None = None) -> dict[str, Any]:
    """Download uncovered completed UTC days, then verify coverage again."""
    root = data_root().resolve()
    before = plan_archive_sync(start, end, root=root)
    if before["missing_segment_files"]:
        details = "; ".join(
            f"{x['name']}: {', '.join(x['missing'])}" for x in before["missing_segment_files"][:4]
        )
        raise ValueError(
            "Archive catalog references segment(s) whose normalized files are missing. "
            "Automatic append cannot safely replace an existing migrated segment: " + details
        )
    if before["unresolved_ranges"] and not before["download_ranges"]:
        raise ValueError(
            "Requested archive range includes an incomplete UTC day. Automatic history download only downloads completed UTC dates."
        )
    if before["download_ranges"] and not before["module_available"]:
        raise ValueError(
            f"Missing archive utility: {before['module_path']}. Expected backtest.history_archive in the repository."
        )

    ranges = [SyncRange(date.fromisoformat(x["start_date"]), date.fromisoformat(x["end_date"])) for x in before["download_ranges"]]
    for index, item in enumerate(ranges, 1):
        if progress:
            progress(
                f"Downloading missing completed history {index}/{len(ranges)}: {item.start_date} → {item.end_date}…",
                3.0 + (index - 1) / max(1, len(ranges)) * 5.0,
                "DATA_SYNC",
                "Refresh archive catalog",
            )
        _run_sync_range(
            root,
            item,
            (lambda msg: progress(msg, 3.0 + index / max(1, len(ranges)) * 5.0, "DATA_SYNC", "Refresh archive catalog")) if progress else None,
        )

    after = plan_archive_sync(start, end, root=root)
    if after["catalog_gaps"] or after["missing_segment_files"]:
        unresolved_text = ", ".join(
            f"{x['start']} → {x['end_exclusive']}" for x in after["catalog_gaps"][:4]
        )
        if after["unresolved_ranges"]:
            unresolved_text += " (includes an incomplete UTC day)"
        raise ValueError("Archive is still incomplete after sync: " + unresolved_text)
    return {"downloaded": bool(ranges), "ranges": [x.as_dict() for x in ranges], "plan_before": before, "plan_after": after}
