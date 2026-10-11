from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .data import timestamp_ns
from .providers.delta_india import DeltaPublicClient, sync_historical_dataset


UTC = timezone.utc
DEFAULT_ARCHIVE = Path("backtest/data/delta-history")
CATALOG_NAME = "catalog.json"


@dataclass(frozen=True)
class ArchiveSegment:
    name: str
    directory: Path
    start: str
    end: str


LEGACY_SEGMENTS = (
    ArchiveSegment(
        "2025",
        Path("backtest/data/delta-2025-01-01_2026-01-01"),
        "2025-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-01_07",
        Path("backtest/data/delta-2026-01-01_08-01"),
        "2026-01-01T00:00:00Z",
        "2026-08-01T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-08-01_23",
        Path("backtest/data/delta-holdout-2026-07-25_08-24"),
        "2026-08-01T00:00:00Z",
        "2026-08-24T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-08-24_09-22",
        Path("backtest/data/delta-2026-09-15_22"),
        "2026-08-24T00:00:00Z",
        "2026-09-23T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-09-23",
        Path("backtest/data/delta-2026-09-23"),
        "2026-09-23T00:00:00Z",
        "2026-09-24T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-09-24_30",
        Path("backtest/data/delta-2026-09-24-to-26"),
        "2026-09-24T00:00:00Z",
        "2026-10-01T00:00:00Z",
    ),
    ArchiveSegment(
        "2026-10-01_03",
        Path("backtest/data/delta-2026-10-01-to-03"),
        "2026-10-01T00:00:00Z",
        "2026-10-04T00:00:00Z",
    ),
)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def load_catalog(root: Path = DEFAULT_ARCHIVE) -> tuple[ArchiveSegment, ...]:
    path = root / CATALOG_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments: list[ArchiveSegment] = []
    for raw in payload.get("segments", []):
        directory = root / str(raw["directory"])
        segments.append(
            ArchiveSegment(
                str(raw["name"]),
                directory,
                str(raw["start"]),
                str(raw["end_exclusive"]),
            )
        )
    return tuple(sorted(segments, key=lambda item: (item.start, item.end, item.name)))


def write_catalog(
    root: Path = DEFAULT_ARCHIVE,
    segments: tuple[ArchiveSegment, ...] | None = None,
) -> Path:
    if segments is None:
        segments = load_catalog(root) if (root / CATALOG_NAME).exists() else ()
    ordered = tuple(sorted(segments, key=lambda item: (item.start, item.end, item.name)))
    payload = {
        "format_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "source": "delta_india_public_history",
        "fidelity": "LOW_FIDELITY_SYNTHETIC_BBO",
        "segments": [
            {
                "name": segment.name,
                "directory": segment.directory.relative_to(root).as_posix(),
                "start": segment.start,
                "end_exclusive": segment.end,
            }
            for segment in ordered
        ],
    }
    root.mkdir(parents=True, exist_ok=True)
    path = root / CATALOG_NAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def migrate(root: Path = DEFAULT_ARCHIVE) -> tuple[ArchiveSegment, ...]:
    data_root = Path("backtest/data").resolve()
    root = root.resolve()
    if not _inside(root, data_root):
        raise ValueError(f"archive must stay inside {data_root}")
    segment_root = root / "segments"
    segment_root.mkdir(parents=True, exist_ok=True)

    migrated: list[ArchiveSegment] = []
    for legacy in LEGACY_SEGMENTS:
        source = legacy.directory.resolve()
        destination = segment_root / legacy.name
        if not _inside(source, data_root) or not _inside(destination, data_root):
            raise ValueError("refusing to move a dataset outside backtest/data")
        if destination.exists() and source.exists():
            try:
                if source.samefile(destination):
                    migrated.append(
                        ArchiveSegment(legacy.name, destination, legacy.start, legacy.end)
                    )
                    continue
            except OSError:
                pass
            raise FileExistsError(f"both datasets exist: {source} and {destination}")
        if source.exists():
            shutil.move(str(source), str(destination))
            print(f"[moved] {source} -> {destination}", flush=True)
        elif not destination.exists():
            raise FileNotFoundError(f"dataset is missing: {source}")
        migrated.append(
            ArchiveSegment(legacy.name, destination, legacy.start, legacy.end)
        )
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(source), str(destination)],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            source.symlink_to(destination, target_is_directory=True)
        print(f"[compatibility link] {source} -> {destination}", flush=True)

    write_catalog(root, tuple(migrated))
    return tuple(migrated)


def _month_interval(value: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM") from exc
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _retry(
    operation: Callable[[], dict[str, Any]],
    attempts: int,
    wait_seconds: float,
) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except RuntimeError:
            if attempt == attempts:
                raise
            delay = min(wait_seconds * 2 ** (attempt - 1), 60.0)
            print(f"[retry] resuming in {delay:.0f}s ({attempt + 1}/{attempts})")
            time.sleep(delay)
    raise AssertionError("retry loop ended unexpectedly")


def sync_segment(
    root: Path,
    start_date: date,
    end_date_exclusive: date,
    *,
    refresh: bool = False,
    attempts: int = 20,
    wait_seconds: float = 15.0,
) -> ArchiveSegment:
    if end_date_exclusive <= start_date:
        raise ValueError("end date must be later than start date")
    if end_date_exclusive > datetime.now(UTC).date():
        raise ValueError("end date must be a completed UTC date")
    start_text = f"{start_date.isoformat()}T00:00:00Z"
    end_text = f"{end_date_exclusive.isoformat()}T00:00:00Z"
    name = (
        f"{start_date:%Y-%m}"
        if end_date_exclusive == _month_interval(f"{start_date:%Y-%m}")[1]
        and start_date.day == 1
        else f"{start_date.isoformat()}_{(end_date_exclusive - timedelta(days=1)).isoformat()}"
    )
    directory = root / "segments" / name
    existing = load_catalog(root) if (root / CATALOG_NAME).exists() else ()
    requested_start = _parse_timestamp(start_text)
    requested_end = _parse_timestamp(end_text)
    retained: list[ArchiveSegment] = []
    for item in existing:
        item_start = _parse_timestamp(item.start)
        item_end = _parse_timestamp(item.end)
        overlaps = item_start < requested_end and requested_start < item_end
        contained = requested_start <= item_start and item_end <= requested_end
        if overlaps and not contained and item.name != name:
            raise ValueError(
                "requested range partially overlaps existing segment "
                f"{item.name}: {item.start} to {item.end}"
            )
        if not contained and item.name != name:
            retained.append(item)
    client = DeltaPublicClient("https://api.india.delta.exchange")
    counts = _retry(
        lambda: sync_historical_dataset(
            client,
            directory,
            start=timestamp_ns(start_text) // 1_000_000_000,
            end=timestamp_ns(end_text) // 1_000_000_000,
            warmup_bars=150,
            candle_seconds=300,
            option_resolution="1m",
            estimated_spread_percent=1.0,
            expiry_horizon_days=3,
            strikes_around_atm=3,
            min_days_to_expiry=1,
            allow_same_day_expiry=False,
            refresh=refresh,
            progress=lambda message: print(message, flush=True),
        ),
        attempts,
        wait_seconds,
    )
    manifest = {
        "source": "delta_india_public_history",
        "generated_at": datetime.now(UTC).isoformat(),
        "start": start_text,
        "end_exclusive": end_text,
        "historical_option_bbo_included": False,
        "execution_prices": "option candle close with 1% synthetic spread",
        "warning": "LOW_FIDELITY: estimated quotes are not historical L1 observations.",
        **counts,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sync_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    segment = ArchiveSegment(name, directory, start_text, end_text)
    write_catalog(root, tuple(retained) + (segment,))
    return segment


def _print_status(root: Path) -> None:
    segments = load_catalog(root)
    print(f"Archive: {root.resolve()}")
    previous_end: datetime | None = None
    for segment in segments:
        start = _parse_timestamp(segment.start)
        if previous_end is not None and start > previous_end:
            print(f"GAP: {_iso(previous_end)} -> {_iso(start)}")
        elif previous_end is not None and start < previous_end:
            print(f"OVERLAP: {segment.name} starts before {_iso(previous_end)}")
        print(f"{segment.start} -> {segment.end}  {segment.directory}")
        previous_end = max(previous_end, _parse_timestamp(segment.end)) if previous_end else _parse_timestamp(segment.end)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the unified Delta history archive")
    parser.add_argument("--root", type=Path, default=DEFAULT_ARCHIVE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="Move existing datasets into the archive")
    subparsers.add_parser("status", help="Show catalog coverage")
    sync_parser = subparsers.add_parser("sync", help="Download or resume a history shard")
    sync_parser.add_argument("--month", help="Calendar month in YYYY-MM format")
    sync_parser.add_argument("--start-date", type=date.fromisoformat)
    sync_parser.add_argument("--end-date", type=date.fromisoformat, help="Inclusive UTC date")
    sync_parser.add_argument(
        "--through-yesterday",
        action="store_true",
        help="Append missing completed UTC days after the catalog's latest segment",
    )
    sync_parser.add_argument("--refresh", action="store_true")
    sync_parser.add_argument("--attempts", type=int, default=20)
    sync_parser.add_argument("--retry-wait-seconds", type=float, default=15.0)
    args = parser.parse_args()

    if args.command == "migrate":
        migrate(args.root)
        _print_status(args.root)
        return
    if args.command == "status":
        _print_status(args.root)
        return

    date_range_requested = bool(args.start_date or args.end_date)
    modes = sum((bool(args.month), date_range_requested, args.through_yesterday))
    if modes != 1:
        parser.error(
            "sync requires exactly one of --month, --through-yesterday, or "
            "--start-date with --end-date"
        )
    if args.month:
        start_date, end_date_exclusive = _month_interval(args.month)
    elif args.through_yesterday:
        catalog = load_catalog(args.root)
        if not catalog:
            parser.error("--through-yesterday requires an existing archive catalog")
        start_date = max(_parse_timestamp(item.end) for item in catalog).date()
        end_date_exclusive = datetime.now(UTC).date()
        if start_date >= end_date_exclusive:
            print("Archive is already current through yesterday.")
            return
    else:
        if args.start_date is None or args.end_date is None:
            parser.error("--start-date and --end-date must be used together")
        start_date = args.start_date
        end_date_exclusive = args.end_date + timedelta(days=1)
    segment = sync_segment(
        args.root,
        start_date,
        end_date_exclusive,
        refresh=args.refresh,
        attempts=args.attempts,
        wait_seconds=args.retry_wait_seconds,
    )
    print(f"Dataset ready: {segment.directory}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from None
