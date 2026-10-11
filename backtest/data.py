from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc


def timestamp_ns(value: str) -> int:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1_000_000_000)


@dataclass(frozen=True)
class UnderlyingBarRow:
    timestamp_ns: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OptionSpec:
    symbol: str
    source_symbol: str
    expiry: str
    strike: float
    option_type: str
    activation_ns: int
    expiration_ns: int
    price_precision: int
    size_precision: int
    price_increment: float
    size_increment: float
    lot_size: float
    min_quantity: float
    contract_value: float


@dataclass(frozen=True)
class OptionQuoteRow:
    timestamp_ns: int
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    volume: float | None
    open_interest: float | None
    source_event: str = ""


@dataclass(frozen=True)
class HistoricalDataset:
    bars: tuple[UnderlyingBarRow, ...]
    options: tuple[OptionSpec, ...]
    quotes: tuple[OptionQuoteRow, ...]


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required historical data file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_dataset(directory: str | Path, start_ns: int, end_ns: int) -> HistoricalDataset:
    root = Path(directory)
    bars = tuple(
        UnderlyingBarRow(
            timestamp_ns(row["timestamp"]),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row.get("volume") or 0.0),
        )
        for row in _rows(root / "underlying_bars.csv")
        if start_ns <= timestamp_ns(row["timestamp"]) < end_ns
    )
    options = tuple(
        OptionSpec(
            symbol=row["symbol"],
            source_symbol=row.get("source_symbol") or row["symbol"],
            expiry=row["expiry"],
            strike=float(row["strike"]),
            option_type=row["option_type"].upper(),
            activation_ns=timestamp_ns(row["activation"]),
            expiration_ns=timestamp_ns(row["expiration"]),
            price_precision=int(row["price_precision"]),
            size_precision=int(row["size_precision"]),
            price_increment=float(row["price_increment"]),
            size_increment=float(row["size_increment"]),
            lot_size=float(row["lot_size"]),
            min_quantity=float(row["min_quantity"]),
            contract_value=float(row["contract_value"]),
        )
        for row in _rows(root / "option_instruments.csv")
    )
    quotes = tuple(
        OptionQuoteRow(
            timestamp_ns(row["timestamp"]),
            row["symbol"],
            float(row["bid"]),
            float(row["ask"]),
            float(row["bid_size"]),
            float(row["ask_size"]),
            _optional_float(row.get("volume")),
            _optional_float(row.get("open_interest")),
            row.get("source_event", ""),
        )
        for row in _rows(root / "option_quotes.csv")
        if start_ns <= timestamp_ns(row["timestamp"]) < end_ns
    )
    dataset = HistoricalDataset(bars, options, quotes)
    validate_dataset(dataset)
    return dataset


def validate_dataset(dataset: HistoricalDataset) -> None:
    if not dataset.bars:
        raise ValueError("dataset contains no underlying bars in the configured period")
    if not dataset.options:
        raise ValueError("dataset contains no option instruments")
    if not dataset.quotes:
        raise ValueError("dataset contains no option BBO quotes in the configured period")
    symbols = {item.symbol for item in dataset.options}
    if len(symbols) != len(dataset.options):
        raise ValueError("option instrument symbols must be unique")
    unknown = sorted({row.symbol for row in dataset.quotes} - symbols)
    if unknown:
        raise ValueError(f"quotes reference unknown option symbols: {', '.join(unknown[:5])}")
    for option in dataset.options:
        if option.option_type not in {"CE", "PE"}:
            raise ValueError(f"invalid option_type for {option.symbol}: {option.option_type}")
        if not option.symbol.upper().endswith(option.option_type):
            raise ValueError(f"normalized symbol must end with {option.option_type}: {option.symbol}")
        if option.expiration_ns <= option.activation_ns:
            raise ValueError(f"expiration must follow activation for {option.symbol}")
        if min(option.price_increment, option.size_increment, option.lot_size, option.contract_value) <= 0:
            raise ValueError(f"instrument increments and contract value must be positive: {option.symbol}")
    for quote in dataset.quotes:
        if quote.bid <= 0 or quote.ask <= 0 or quote.bid > quote.ask:
            raise ValueError(f"invalid BBO for {quote.symbol} at {quote.timestamp_ns}")
