from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .providers.delta_india import (
    DeltaPublicClient,
    _normalized_option_symbol,
    _parse_utc,
    _precision,
)
from .r2 import R2Client


QUOTE_FIELDS = [
    "timestamp",
    "symbol",
    "source_event",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
    "volume",
    "open_interest",
]
BAR_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]
PROJECT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env_file(path: Path = PROJECT_ENV_PATH) -> None:
    """Load simple KEY=VALUE settings without overriding the process environment."""
    if not path.is_file():
        return
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid .env entry at {path}:{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid .env variable name at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _remote_prefix(day: date, configured: str) -> str:
    root = configured.strip("/") or "delta-l1"
    return f"{root}/{day:%Y/%m/%d}/"


def download_day(day: date, output: Path, prefix: str) -> dict[str, Any]:
    _load_env_file()
    client = R2Client.from_environment()
    remote = _remote_prefix(day, prefix)
    keys = [key for key in client.list_objects(remote) if key.endswith(".jsonl.gz")]
    if not keys:
        raise RuntimeError(f"no L1 recordings found in R2 below {remote}")
    files: list[dict[str, Any]] = []
    for key in keys:
        relative_key = PurePosixPath(key.removeprefix(remote))
        if relative_key.is_absolute() or ".." in relative_key.parts:
            raise RuntimeError(f"unsafe R2 object key below recording prefix: {key}")
        relative = Path(*relative_key.parts)
        target = output / day.isoformat() / relative
        client.download(key, target)
        files.append({"key": key, "path": str(target), "bytes": target.stat().st_size})
    manifest = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "date": day.isoformat(),
        "remote_prefix": remote,
        "file_count": len(files),
        "files": files,
    }
    manifest_path = output / day.isoformat() / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _paths(value: Path | Iterable[Path]) -> list[Path]:
    if isinstance(value, Path):
        return [value]
    return [Path(item) for item in value]


def _event_files(sources: Path | Iterable[Path]) -> list[Path]:
    paths: set[Path] = set()
    for source in _paths(sources):
        if source.is_file() and source.name.endswith(".jsonl.gz"):
            paths.add(source)
            continue
        if source.is_dir():
            paths.update(source.rglob("*.jsonl.gz"))
            continue
        raise FileNotFoundError(f"recorded L1 input does not exist: {source}")
    return sorted(paths)


def _events(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in {path}:{line_number}") from exc
                if isinstance(event, dict):
                    yield event


def _positive_number(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _optional_number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _load_instruments(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"instrument file has no header: {path}")
        rows = {row["symbol"]: row for row in reader}
        return reader.fieldnames, rows


def _load_cached_product_instruments(
    base: Path,
) -> dict[str, dict[str, str]]:
    """Load contract metadata which the synthetic dataset did not select.

    Recorded sessions can request a farther expiry than the synthetic dataset's
    ATM universe. The public Delta product cache is authoritative for contract
    identity and avoids requiring unrelated option candle downloads merely to
    make those recorded BBO observations importable.
    """
    instruments: dict[str, dict[str, str]] = {}
    for path in sorted((base / "raw" / "products").glob("BTC-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(products, list):
            continue
        for product in products:
            if not isinstance(product, dict):
                continue
            row = _instrument_from_product(product)
            if row is not None:
                instruments[row["symbol"]] = row
    return instruments


def _instrument_from_product(product: dict[str, Any]) -> dict[str, str] | None:
    contract_type = str(product.get("contract_type") or "")
    if contract_type not in {"call_options", "put_options"}:
        return None
    try:
        source_symbol = str(product["symbol"])
        symbol = _normalized_option_symbol(product)
        activation = _parse_utc(
            str(product.get("launch_time") or product.get("created_at"))
        )
        expiration = _parse_utc(str(product["settlement_time"]))
        strike = float(product["strike_price"])
        tick_size = float(product["tick_size"])
        contract_value = float(product["contract_value"])
    except (KeyError, TypeError, ValueError):
        return None
    if not symbol or strike <= 0 or tick_size <= 0 or contract_value <= 0:
        return None
    return {
        "symbol": symbol,
        "source_symbol": source_symbol,
        "expiry": expiration.strftime("%d%b%y").upper(),
        "strike": str(product["strike_price"]),
        "option_type": "CE" if contract_type == "call_options" else "PE",
        "activation": activation.isoformat().replace("+00:00", "Z"),
        "expiration": expiration.isoformat().replace("+00:00", "Z"),
        "price_precision": str(_precision(tick_size)),
        "size_precision": "0",
        "price_increment": str(product["tick_size"]),
        "size_increment": "1",
        "lot_size": "1",
        "min_quantity": "1",
        "contract_value": str(product["contract_value"]),
    }


def _contract_key(
    expiry: Any,
    strike: Any,
    option_type: Any,
) -> tuple[str, float, str] | None:
    normalized_expiry = re.sub(r"[^A-Z0-9]", "", str(expiry or "").upper())
    normalized_type = str(option_type or "").upper()
    try:
        normalized_strike = float(strike)
    except (TypeError, ValueError):
        return None
    if not normalized_expiry or normalized_type not in {"CE", "PE"}:
        return None
    return normalized_expiry, normalized_strike, normalized_type


def _delta_source_symbol(key: tuple[str, float, str]) -> str:
    expiry, strike, option_type = key
    parsed_expiry = datetime.strptime(expiry, "%d%b%y")
    strike_text = str(int(strike)) if strike.is_integer() else format(strike, "g")
    side = "C" if option_type == "CE" else "P"
    return f"{side}-BTC-{strike_text}-{parsed_expiry:%d%m%y}"


def _event_contract_key(event: dict[str, Any], symbol: str) -> tuple[str, float, str] | None:
    metadata = event.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    key = _contract_key(
        event.get("expiry") or metadata.get("expiry"),
        event.get("strike") or metadata.get("strike"),
        event.get("option_type") or metadata.get("instrumenttype"),
    )
    if key is not None:
        return key
    match = re.fullmatch(
        r"BTC(?P<expiry>\d{2}[A-Z]{3}\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<kind>CE|PE)",
        symbol.upper(),
    )
    if match is None:
        return None
    return _contract_key(match["expiry"], match["strike"], match["kind"])


def import_recordings(
    source: Path | Iterable[Path],
    base: Path | Iterable[Path],
    output: Path,
    assumed_book_size: float = 1.0,
    fetch_missing_products: bool = False,
    public_api_url: str = "https://api.india.delta.exchange",
) -> dict[str, Any]:
    if assumed_book_size <= 0:
        raise ValueError("assumed_book_size must be positive")
    source_paths = _paths(source)
    base_paths = _paths(base)
    paths = _event_files(source_paths)
    if not paths:
        raise RuntimeError("no .jsonl.gz recordings found below the configured inputs")
    fieldnames: list[str] | None = None
    instruments: dict[str, dict[str, str]] = {}
    cached_product_instruments = 0
    base_bars: dict[str, dict[str, str]] = {}
    for base_path in base_paths:
        instrument_path = base_path / "option_instruments.csv"
        bars_path = base_path / "underlying_bars.csv"
        if not instrument_path.is_file() or not bars_path.is_file():
            raise FileNotFoundError(
                f"base dataset {base_path} must contain option_instruments.csv "
                "and underlying_bars.csv"
            )
        current_fields, current_instruments = _load_instruments(instrument_path)
        if fieldnames is None:
            fieldnames = current_fields
        elif current_fields != fieldnames:
            raise ValueError("base datasets use incompatible option instrument columns")
        instruments.update(current_instruments)
        cached = _load_cached_product_instruments(base_path)
        cached_product_instruments += len(set(cached) - set(instruments))
        instruments.update(cached)
        with bars_path.open("r", encoding="utf-8", newline="") as handle:
            base_bars.update(
                {
                    row["timestamp"]: row
                    for row in csv.DictReader(handle)
                    if row.get("timestamp")
                }
            )
    if fieldnames is None:
        raise ValueError("at least one base dataset is required")
    instruments_by_contract = {
        key: symbol
        for symbol, row in instruments.items()
        if (key := _contract_key(row.get("expiry"), row.get("strike"), row.get("option_type")))
        is not None
    }
    fetched_product_instruments = 0
    if fetch_missing_products:
        unresolved: set[tuple[str, float, str]] = set()
        for event in _events(paths):
            if str(event.get("event_type", "")) not in {"quote", "option_chain"}:
                continue
            key = _event_contract_key(event, str(event.get("symbol", "")).strip())
            if key is not None and key not in instruments_by_contract:
                unresolved.add(key)
        client = DeltaPublicClient(public_api_url)
        for key in sorted(unresolved):
            source_symbol = _delta_source_symbol(key)
            row = _instrument_from_product(client.product(source_symbol))
            if row is None:
                raise RuntimeError(f"Delta returned unusable metadata for {source_symbol}")
            instruments[row["symbol"]] = row
            instruments_by_contract[key] = row["symbol"]
            fetched_product_instruments += 1
    quotes: dict[tuple[int, str], tuple[int, dict[str, Any]]] = {}
    recorded_bars: dict[str, dict[str, Any]] = {}
    orders: list[dict[str, Any]] = []
    sessions: dict[str, dict[str, Any]] = {}
    inferred_bid_sizes = 0
    inferred_ask_sizes = 0
    event_count = 0
    for event in _events(paths):
        event_count += 1
        event_type = str(event.get("event_type", ""))
        session_id = str(event.get("session_id", "")).strip()
        received_at = str(event.get("received_at", "")).strip()
        if session_id and received_at:
            session = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "start": received_at,
                    "end": received_at,
                    "events": 0,
                    "event_types": {},
                },
            )
            session["start"] = min(session["start"], received_at)
            session["end"] = max(session["end"], received_at)
            session["events"] += 1
            type_counts = session["event_types"]
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
            if event_type == "session_start":
                strategy_name = str(event.get("strategy", "")).strip()
                if strategy_name:
                    session["strategy"] = strategy_name
                strategy_config = event.get("config")
                if isinstance(strategy_config, dict) and strategy_config:
                    session["strategy_config"] = strategy_config
        if event_type.startswith("order_"):
            orders.append(event)
        if event_type == "underlying_candle":
            timestamp = str(event.get("timestamp", "")).strip()
            try:
                bar = {
                    "timestamp": timestamp,
                    "open": float(event["open"]),
                    "high": float(event["high"]),
                    "low": float(event["low"]),
                    "close": float(event["close"]),
                    "volume": float(event.get("volume") or 0.0),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp and min(bar["open"], bar["high"], bar["low"], bar["close"]) > 0:
                recorded_bars[timestamp] = bar
        if event_type not in {"quote", "option_chain"}:
            continue
        recorded_symbol = str(event.get("symbol", "")).strip()
        symbol = recorded_symbol
        if symbol not in instruments:
            contract_key = _event_contract_key(event, symbol)
            symbol = instruments_by_contract.get(contract_key, symbol)
        bid = _positive_number(event.get("bid"))
        ask = _positive_number(event.get("ask"))
        if not symbol or bid is None or ask is None or bid > ask:
            continue
        try:
            received_ns = int(event["received_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        timestamp = received_at
        if not timestamp:
            timestamp = datetime.fromtimestamp(
                received_ns / 1_000_000_000, timezone.utc
            ).isoformat().replace("+00:00", "Z")
        bid_size = _positive_number(event.get("bid_size"))
        ask_size = _positive_number(event.get("ask_size"))
        inferred_bid_sizes += int(bid_size is None)
        inferred_ask_sizes += int(ask_size is None)
        row = {
            "timestamp": timestamp,
            "symbol": symbol,
            "source_event": event_type,
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size or assumed_book_size,
            "ask_size": ask_size or assumed_book_size,
            "volume": _optional_number(event.get("volume")),
            "open_interest": _optional_number(event.get("open_interest")),
        }
        priority = 1 if event_type == "quote" else 0
        key = (received_ns, symbol)
        previous = quotes.get(key)
        if previous is None or priority > previous[0]:
            quotes[key] = (priority, row)
    if not quotes:
        raise RuntimeError("recordings contain no valid positive bid/ask observations")
    symbols = {item[1]["symbol"] for item in quotes.values()}
    missing = sorted(symbols - instruments.keys())
    if missing:
        sample = ", ".join(missing[:5])
        raise ValueError(f"base dataset is missing {len(missing)} recorded instruments: {sample}")
    output.mkdir(parents=True, exist_ok=True)
    base_bars.update(recorded_bars)
    with (output / "underlying_bars.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAR_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(base_bars[timestamp] for timestamp in sorted(base_bars))
    with (output / "option_instruments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(instruments[symbol] for symbol in sorted(symbols))
    ordered_quotes = [value[1] for _, value in sorted(quotes.items())]
    with (output / "option_quotes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUOTE_FIELDS)
        writer.writeheader()
        writer.writerows(ordered_quotes)
    if orders:
        with (output / "live_orders.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for event in orders:
                handle.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": [str(path) for path in source_paths],
        "base_dataset": [str(path) for path in base_paths],
        "source_files": len(paths),
        "recorded_events": event_count,
        "quotes": len(ordered_quotes),
        "recorded_underlying_bars": len(recorded_bars),
        "instruments": len(symbols),
        "cached_product_instruments": cached_product_instruments,
        "fetched_product_instruments": fetched_product_instruments,
        "order_events": len(orders),
        "inferred_bid_sizes": inferred_bid_sizes,
        "inferred_ask_sizes": inferred_ask_sizes,
        "assumed_missing_book_size": assumed_book_size,
        "sessions": sorted(sessions.values(), key=lambda item: item["start"]),
        "fidelity": "BBO_FIDELITY",
        "scope": "decision-visible snapshots; not a continuous exchange order-book feed",
    }
    (output / "recording_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download and import session L1 recordings")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="download one UTC date from R2")
    download.add_argument("--date", required=True, type=_date)
    download.add_argument("--output", type=Path, default=Path("backtest/downloads/r2"))
    download.add_argument("--prefix", default=os.getenv("R2_PREFIX", "delta-l1"))
    importer = commands.add_parser("import", help="convert recordings to normalized backtest CSVs")
    importer.add_argument("--input", required=True, type=Path, nargs="+")
    importer.add_argument("--base", required=True, type=Path, nargs="+")
    importer.add_argument("--output", required=True, type=Path)
    importer.add_argument("--assumed-book-size", type=float, default=1.0)
    importer.add_argument(
        "--fetch-missing-products",
        action="store_true",
        help="fetch exact Delta metadata for recorded contracts absent from the base cache",
    )
    importer.add_argument(
        "--public-api-url",
        default="https://api.india.delta.exchange",
    )
    return parser


def main() -> None:
    _load_env_file()
    args = build_parser().parse_args()
    if args.command == "download":
        result = download_day(args.date, args.output, args.prefix)
        print(json.dumps(result, indent=2))
    else:
        result = import_recordings(
            args.input,
            args.base,
            args.output,
            assumed_book_size=args.assumed_book_size,
            fetch_missing_products=args.fetch_missing_products,
            public_api_url=args.public_api_url,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
