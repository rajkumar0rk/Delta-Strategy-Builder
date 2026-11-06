"""Cache-first repair of missing BTCUSD 5m candles in the unified archive.

Only absent candle-close timestamps within the *selected* interval are fetched;
existing candle values, option quotes and catalog entries are never replaced.
All API responses are validated before ANY CSV file is changed.
Run via subprocess from visualizer/backend/app/archive_sync.py.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .providers.delta_india import DeltaPublicClient

UTC = timezone.utc
STEP = 300
HEADER = ("timestamp", "open", "high", "low", "close", "volume")
BASE_URL = "https://api.india.delta.exchange"
MAX_CHUNK_CANDLES = 1440  # 5 UTC days; strictly below provider's ~2000 cap


def _epoch(value: str) -> int:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"BTC candle timestamp must have a UTC offset: {value}")
    return int(dt.astimezone(UTC).timestamp())


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


def _segments(root: Path):
    catalog = root / "catalog.json"
    if not catalog.exists():
        raise ValueError("Missing archive catalog.json; repair catalog coverage first")
    obj = json.loads(catalog.read_text(encoding="utf-8"))
    segments = []
    for segment in obj.get("segments", []):
        a, b = _epoch(segment["start"]), _epoch(segment["end_exclusive"])
        if a >= b:
            raise ValueError(f"Invalid archive segment interval: {segment}")
        relative = Path(str(segment["directory"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Archive segment path must be relative and inside the archive root")
        segments.append((a, b, root / relative / "underlying_bars.csv"))
    return sorted(segments, key=lambda item: (item[0], item[1]))


def _read_existing(path: Path, *, include_rows: bool = False):
    """One linear timestamp scan per segment, and full rows only when writing."""
    present = set()
    rows = {}
    if not path.is_file():
        return rows if include_rows else present
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != HEADER:
            raise ValueError(f"BTC archive has unsupported candle CSV columns: {path}")
        for raw in reader:
            when = _epoch(raw["timestamp"])
            if when % STEP:
                raise ValueError(f"Off-grid BTC candle close in {path}: {raw['timestamp']}")
            if when in present:
                raise ValueError(f"Duplicate BTC candle close in {path}: {raw['timestamp']}")
            present.add(when)
            if include_rows:
                rows[when] = raw
    return rows if include_rows else present


def missing_candles(root: Path, start: str, end: str):
    """Return (missing close timestamp, target CSV) without network calls."""
    first, last = _epoch(start), _epoch(end)
    if last <= first:
        raise ValueError("Selected BTC candle end must be later than start")
    segments = _segments(Path(root))
    relevant = [seg for seg in segments if seg[1] > first - STEP and seg[0] < last]
    if not relevant:
        raise ValueError("No archive segment covers selected BTC candles; repair catalog first")
    present = set()
    for a, b, path in relevant:
        present.update(_read_existing(path))
    starts = [seg[0] for seg in relevant]
    missing = []
    first_close = (first + STEP - 1) // STEP * STEP
    for close in range(first_close, last, STEP):
        if close in present:
            continue
        # Assign the missing candle to the appropriate catalogued segment.
        # A timestamp on the boundary can be the last close of the prior
        # segment or the first close of the next one; both are read by DataStore.
        idx = bisect.bisect_right(starts, close) - 1
        chosen = None
        if idx >= 0:
            a, b, path = relevant[idx]
            if a <= close < b:
                chosen = path
        if chosen is None and idx >= 0:
            a, b, path = relevant[idx]
            if close == b:
                chosen = path
        if chosen is None:
            raise ValueError(
                f"BTC_CANDLE_CATALOG_GAP: no archive segment owns missing "
                f"5m close {_iso(close)}; repair catalog coverage first"
            )
        missing.append((close, chosen))
    return missing


def _normalize_candle(item: dict, expected_close: int):
    try:
        opened = int(item["time"])
        prices = [float(item[key]) for key in HEADER[1:5]]
        volume = float(item.get("volume") or 0.0)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Invalid Delta BTCUSD 5m candle payload") from exc
    if opened + STEP != expected_close or opened % STEP:
        raise ValueError(f"Delta returned an unexpected candle timestamp for {_iso(expected_close)}")
    o, h, l, c = prices
    if (not all(math.isfinite(v) for v in (*prices, volume))
            or min(prices) <= 0 or volume < 0
            or h < max(o, c) or l > min(o, c) or h < l):
        raise ValueError(f"Delta returned invalid BTCUSD OHLCV for {_iso(expected_close)}")
    return dict(zip(HEADER, (_iso(expected_close), o, h, l, c, volume)))


def repair_missing_btc_candles(
    root: Path, start: str, end: str, *, client=None,
    progress: Callable[[str], None] | None = None,
    now: datetime | None = None,
):
    """One read-through cache pass; no requests or writes if already complete."""
    root = Path(root)
    missing = missing_candles(root, start, end)
    if not missing:
        if progress:
            progress("BTC 5m candle cache complete — no network requests")
        return {"downloaded": 0, "api_requests": 0, "reused": True}
    latest = now or datetime.now(UTC)
    if latest.tzinfo is None:
        raise ValueError("now must be timezone aware")
    last_completed = int(latest.astimezone(UTC).timestamp()) // STEP * STEP
    if missing[-1][0] > last_completed:
        raise ValueError(
            f"BTC_CANDLE_NOT_COMPLETE: latest missing 5m close {_iso(missing[-1][0])} "
            f"is not completed yet; choose an earlier range"
        )
    client = client or DeltaPublicClient(BASE_URL)
    if progress:
        progress(f"BTC 5m archive cache has {len(missing)} missing candle(s); downloading only gaps")
    # Partition by adjacent missing close AND destination segment, then cap
    # each API call at five days. Never fetch an already-cached interval.
    groups = []
    batch = []
    for item in missing:
        if batch and (item[1] != batch[-1][1]
                      or item[0] != batch[-1][0] + STEP
                      or len(batch) >= MAX_CHUNK_CANDLES):
            groups.append(batch)
            batch = []
        batch.append(item)
    if batch:
        groups.append(batch)

    # Stage all API observations in memory first. A failure in any group leaves
    # every existing CSV byte-for-byte intact. Subsequent runs can retry.
    additions = defaultdict(dict)
    for index, group in enumerate(groups, 1):
        first, last = group[0][0], group[-1][0]
        expected = {stamp for stamp, _ in group}
        candles = client.candles("BTCUSD", first - STEP, last, "5m")
        got = {}
        for item in candles:
            try:
                close = int(item["time"]) + STEP
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError("Delta returned malformed BTC candle timestamps") from exc
            if close in expected:
                normalized = _normalize_candle(item, close)
                if close in got and got[close] != normalized:
                    raise ValueError(f"Conflicting Delta BTC candle observations at {_iso(close)}")
                got[close] = normalized
        if expected != set(got):
            missed = sorted(expected.difference(got))
            raise RuntimeError(
                f"BTC_CANDLE_DOWNLOAD_INCOMPLETE: Delta returned {len(got)}/"
                f"{len(expected)} missing 5m candles; first absent close "
                f"{_iso(missed[0]) if missed else '?'}; cached CSVs unchanged"
            )
        additions[group[0][1]].update(got)
        if progress:
            progress(f"Fetched BTC candle gap {index}/{len(groups)} ({len(got)} bars)")

    # Preserve all existing cached candles, using atomic per-file replacement.
    # A mid-write failure can leave some *complete* repaired files, never a
    # truncated CSV, and a later run resumes from the remaining missing closes.
    for path, extra in additions.items():
        old = _read_existing(path, include_rows=True)
        overlap = set(old).intersection(extra)
        if overlap:
            raise RuntimeError(f"BTC candles appeared during sync: {path}; retry safely")
        merged = {**old, **extra}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(HEADER), lineterminator="\n")
                writer.writeheader()
                for stamp in sorted(merged):
                    writer.writerow(merged[stamp])
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"downloaded": len(missing), "api_requests": len(groups),
            "touched_files": len(additions), "reused": False}



def append_uncovered_btc_intervals(
    root: Path, gaps: list[tuple[str, str]], *,
    client=None, progress: Callable[[str], None] | None = None,
    now: datetime | None = None,
):
    """Append only missing catalog intervals, downloading BTC candles alone.

    Existing archive segment intervals/files are never rewritten. A failed
    request never adds a partly complete segment to catalog.json.
    """
    from .history_archive import ArchiveSegment, load_catalog, write_catalog

    root = Path(root).resolve()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    completed = int(now.timestamp()) // STEP * STEP
    current = list(load_catalog(root)) if (root / "catalog.json").exists() else []
    intervals = [(int(_epoch(item.start)), int(_epoch(item.end))) for item in current]
    requested = []
    for start, end in gaps:
        a, b = _epoch(start), _epoch(end)
        if b <= a or a % STEP or b % STEP:
            raise ValueError("BTC catalog gaps must be nonempty UTC-aligned 5m intervals")
        if b > completed:
            raise ValueError("BTC_CANDLE_NOT_COMPLETE: missing interval includes an incomplete candle")
        if any(a < y and x < b for x, y in intervals):
            raise ValueError("BTC_CATALOG_GAP_OVERLAP: refusing to modify an existing archive segment")
        if any(a < y and x < b for x, y in requested):
            raise ValueError("BTC_CATALOG_GAP_OVERLAP: requested intervals overlap")
        requested.append((a, b))

    if not requested:
        return {"appended_segments": 0, "downloaded": 0}
    client = client or DeltaPublicClient(BASE_URL)
    staging = []
    created_directories = []
    # No downloads or catalog edits for an already-complete interval.
    try:
        for a, b in requested:
            rows = {}
            # Use close timestamps [a,b); Delta API timestamps candle opens.
            for first_close in range(a, b, MAX_CHUNK_CANDLES * STEP):
                end_close = min(b, first_close + MAX_CHUNK_CANDLES * STEP)
                response = client.candles("BTCUSD", first_close - STEP, end_close - STEP, "5m")
                expected = set(range(first_close, end_close, STEP))
                got = {}
                for item in response:
                    close = int(item["time"]) + STEP
                    if close in expected:
                        normalized = _normalize_candle(item, close)
                        if close in got and got[close] != normalized:
                            raise ValueError("Conflicting Delta BTC candle responses")
                        got[close] = normalized
                if set(got) != expected:
                    raise RuntimeError(
                        f"BTC_CANDLE_DOWNLOAD_INCOMPLETE: {len(expected-set(got))} "
                        f"missing 5m close(s) in {_iso(first_close)} → {_iso(end_close)}; "
                        f"catalog unchanged"
                    )
                rows.update(got)
            label = f"btc-only-{datetime.fromtimestamp(a, UTC):%Y%m%dT%H%M}-" \
                    f"{datetime.fromtimestamp(b, UTC):%Y%m%dT%H%M}"
            target = root / "segments" / label
            if target.exists():
                raise FileExistsError(f"Uncatalogued BTC gap segment already exists: {target}")
            staging.append((a, b, target, rows))
            if progress:
                progress(f"Fetched {len(rows)} missing BTC 5m bars for {_iso(a)} → {_iso(b)}")

        # Stage all complete files before publishing any new catalog reference.
        segments = []
        for a, b, target, rows in staging:
            target.mkdir(parents=True, exist_ok=False)
            created_directories.append(target)
            output = target / "underlying_bars.csv"
            temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
            with temporary.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(HEADER), lineterminator="\n")
                writer.writeheader()
                for close in sorted(rows):
                    writer.writerow(rows[close])
            os.replace(temporary, output)
            segments.append(ArchiveSegment(target.name, target, _iso(a), _iso(b)))
        write_catalog(root, tuple(current) + tuple(segments))
        return {"appended_segments": len(segments), "downloaded": sum(len(x[3]) for x in staging)}
    except BaseException:
        # If a CSV/catalog write fails, don't strand a partial segment that
        # blocks future retries. Never remove a directory referenced by the
        # canonical catalog (including the rare case of a late exception).
        referenced = set()
        try:
            if (root / "catalog.json").exists():
                referenced = {
                    item.directory.resolve()
                    for item in load_catalog(root)
                }
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            # If the catalog itself is unreadable, do not delete anything.
            referenced = {item.resolve() for item in created_directories}
        for directory in created_directories:
            if directory.resolve() not in referenced:
                shutil.rmtree(directory)
        raise


def append_btc_catalog_gaps(
    root: Path, start: str, end: str, *,
    client=None, now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
):
    """Find uncovered archive intervals; do not download existing intervals."""
    root = Path(root)
    a, b = _epoch(start), _epoch(end)
    if b <= a:
        raise ValueError("Invalid requested BTC history range")
    intervals = [(x, y) for x, y, _ in _segments(root)] if (root / "catalog.json").exists() else []
    cursor = a
    gaps = []
    for x, y in intervals:
        if y <= cursor or x >= b:
            continue
        if x > cursor:
            gaps.append((_iso(cursor), _iso(min(x, b))))
        cursor = max(cursor, y)
    if cursor < b:
        gaps.append((_iso(cursor), _iso(b)))
    return append_uncovered_btc_intervals(root, gaps, client=client,
                                          now=now, progress=progress)

def main():
    parser = argparse.ArgumentParser(description="Repair only missing cached BTCUSD 5m candles")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--append-catalog-gaps", action="store_true",
                        help="Append missing catalog intervals using BTC candles alone")
    args = parser.parse_args()
    if args.append_catalog_gaps:
        result = append_btc_catalog_gaps(
            args.root, args.start, args.end, progress=lambda text: print(text, flush=True))
    else:
        result = repair_missing_btc_candles(
            args.root, args.start, args.end, progress=lambda text: print(text, flush=True))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
