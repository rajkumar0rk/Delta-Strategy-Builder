"""Free, incremental Delta India futures *observation* history.

Reuses the repository's authenticated-free DeltaPublicClient, with no new
dependency and no duplicate underlying BTC OHLCV downloads.

Raw FUNDING:BTCUSD OHLC candles are indicative sampled rates, NOT certified
funding *settlement* cash flows; never write futures_funding.csv here.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Callable

from .providers.delta_india import DeltaPublicClient

UTC = timezone.utc
RESOLUTION_SECONDS = 60
DAY_SECONDS = 86_400
BASE_URL = "https://api.india.delta.exchange"
# The Delta BTCUSD index is an exception to the ordinary .DE<asset>USD rule.
SERIES = {
    "mark": "MARK:BTCUSD",
    "index": ".DEXBTUSD",
    "funding_rate": "FUNDING:BTCUSD",
}
HEADER = ("timestamp", "open", "high", "low", "close", "volume")


def _utc_epoch(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Futures history range must have an explicit UTC offset")
    return int(dt.astimezone(UTC).timestamp())


def _day_file(root: Path, kind: str, epoch_day: int) -> Path:
    date = datetime.fromtimestamp(epoch_day, UTC).strftime("%Y-%m-%d")
    return root / "futures" / kind / f"{date}.csv"


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _normalize(rows: list[dict], *, symbol: str, day: int, dense: bool) -> list[list[str | float]]:
    indexed: dict[int, list[str | float]] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError(f"Invalid {symbol} candle response")
        try:
            stamp = int(item["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid {symbol} candle timestamp") from exc
        if stamp < day or stamp >= day + DAY_SECONDS:
            continue
        if stamp % RESOLUTION_SECONDS:
            raise RuntimeError(f"Off-grid {symbol} minute candle at {stamp}")
        fields = []
        for key in ("open", "high", "low", "close", "volume"):
            try:
                value = float(item[key]) if key in item and item[key] is not None else (0.0 if key == "volume" else float("nan"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid {symbol} {key} value at {stamp}") from exc
            if not math.isfinite(value):
                raise RuntimeError(f"Nonfinite {symbol} {key} at {stamp}")
            fields.append(value)
        if dense and (min(fields[:4]) <= 0 or fields[1] < max(fields[0], fields[3]) or fields[2] > min(fields[0], fields[3])):
            raise RuntimeError(f"Invalid {symbol} price candle OHLC at {stamp}")
        if stamp in indexed and indexed[stamp][1:] != fields:
            raise RuntimeError(f"Conflicting duplicate {symbol} candle at {stamp}")
        # Delta candles are stamped at OPEN; normalized CSV uses completed close.
        indexed[stamp] = [_iso(stamp + RESOLUTION_SECONDS), *fields]
    if dense:
        expected = set(range(day, day + DAY_SECONDS, RESOLUTION_SECONDS))
        if indexed.keys() != expected:
            missing = len(expected - indexed.keys())
            raise RuntimeError(f"{symbol} incomplete 1m coverage for {_iso(day)[:10]}: {missing} missing candles")
    return [indexed[t] for t in sorted(indexed)]


def _valid_file(path: Path, day: int, dense: bool) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != HEADER:
                return False
            count, first, last, previous = 0, None, None, None
            for row in reader:
                ts = _utc_epoch(row["timestamp"]) - RESOLUTION_SECONDS
                if ts < day or ts >= day + DAY_SECONDS or (previous is not None and ts <= previous):
                    return False
                if dense and ts != day + count * RESOLUTION_SECONDS:
                    return False
                previous = last = ts
                if first is None:
                    first = ts
                count += 1
            return (count == DAY_SECONDS // RESOLUTION_SECONDS and first == day
                    and last == day + DAY_SECONDS - RESOLUTION_SECONDS) if dense else True
    except (OSError, UnicodeError, ValueError, KeyError):
        return False


def sync_futures_observations(
    root: Path,
    start: str,
    end: str,
    *,
    client: DeltaPublicClient | None = None,
    progress: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> dict:
    """Download only missing *complete* UTC day-shards; reuse existing files.

    A failed or truncated response never replaces an existing valid shard.
    This intentionally does not modify catalog.json or existing BTC bars.
    """
    first, last = _utc_epoch(start), _utc_epoch(end)
    if last <= first:
        raise ValueError("End must follow start")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    completed_end = int(datetime(now.year, now.month, now.day, tzinfo=UTC).timestamp())
    first_day = first - first % DAY_SECONDS
    last_day = (last + DAY_SECONDS - 1) // DAY_SECONDS * DAY_SECONDS
    if last_day > completed_end:
        raise ValueError("Futures observation auto-download requires fully completed UTC days; shorten the backtest end")
    client = client or DeltaPublicClient(BASE_URL)
    downloaded: dict[str, int] = {kind: 0 for kind in SERIES}
    reused: dict[str, int] = {kind: 0 for kind in SERIES}
    root = Path(root)
    days = range(first_day, last_day, DAY_SECONDS)
    for day in days:
        for kind, symbol in SERIES.items():
            output = _day_file(root, kind, day)
            dense = kind != "funding_rate"
            if _valid_file(output, day, dense):
                reused[kind] += 1
                continue
            if progress:
                progress(f"Free Delta futures {kind} 1m: {_iso(day)[:10]}")
            # One complete UTC day is 1440 one-minute candles (<2000 API cap).
            observations = client.candles(symbol, day, day + DAY_SECONDS, "1m")
            normalized = _normalize(observations, symbol=symbol, day=day, dense=dense)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
            try:
                with temporary.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(HEADER)
                    writer.writerows(normalized)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
            downloaded[kind] += 1
            time.sleep(0.05)
    return {"root": str(root / "futures"), "downloaded_days_by_series": downloaded,
            "reused_days_by_series": reused, "funding_is_settlement_ledger": False,
            "price_source": "delta_india_public_history",
            "index_symbol": ".DEXBTUSD"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync FREE historical Delta futures observations (never orderbook or settlement ledger)")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--start", required=True, help="UTC ISO8601 with timezone")
    parser.add_argument("--end", required=True, help="UTC ISO8601 exclusive")
    args = parser.parse_args()
    result = sync_futures_observations(args.root, args.start, args.end, progress=lambda s: print(s, flush=True))
    print(result, flush=True)


if __name__ == "__main__":
    main()
