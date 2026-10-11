from __future__ import annotations

import csv
import bisect
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


UTC = timezone.utc


class DeltaPublicClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        request = urllib.request.Request(
            f"{self.base_url}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "delta-strategy-backtest/0.1"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read(500).decode("utf-8", errors="replace")
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                    raise RuntimeError(f"Delta API returned HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, OSError) as exc:
                if attempt == 3:
                    reason = getattr(exc, "reason", str(exc))
                    raise RuntimeError(f"Delta API request failed: {reason}") from exc
            time.sleep(0.5 * (2 ** attempt))
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError(f"Delta API returned an unsuccessful response for {path}")
        return payload

    def candles(self, symbol: str, start: int, end: int, resolution: str = "5m") -> list[dict[str, Any]]:
        payload = self.get("/v2/history/candles", {
            "resolution": resolution,
            "symbol": symbol,
            "start": start,
            "end": end,
        })
        result = payload.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Delta candle response did not contain a result list")
        return result

    def products(
        self,
        contract_types: str,
        states: str,
        *,
        expiry: str | None = None,
        underlying_asset_symbols: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        after: str | None = None
        while True:
            payload = self.get("/v2/products", {
                "contract_types": contract_types,
                "states": states,
                "page_size": 100,
                "after": after,
                "expiry": expiry,
                "underlying_asset_symbols": underlying_asset_symbols,
            })
            result = payload.get("result")
            if not isinstance(result, list):
                raise RuntimeError("Delta products response did not contain a result list")
            yield from (item for item in result if isinstance(item, dict))
            meta = payload.get("meta") or {}
            next_after = meta.get("after")
            if not next_after or next_after == after or not result:
                return
            after = str(next_after)
            time.sleep(0.05)

    def product(self, symbol: str) -> dict[str, Any]:
        payload = self.get(
            f"/v2/products/{urllib.parse.quote(symbol, safe='')}",
            {},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Delta product response did not contain {symbol}")
        return result


def _iso_utc(epoch_seconds: int | float) -> str:
    return datetime.fromtimestamp(float(epoch_seconds), UTC).isoformat().replace("+00:00", "Z")


def download_underlying_bars(
    client: DeltaPublicClient,
    symbol: str,
    start: int,
    end: int,
    output: Path,
) -> int:
    # Delta silently truncates oversized five-minute candle responses. Five
    # days is 1,440 bars and remains below the observed provider cap.
    chunk_seconds = 5 * 24 * 60 * 60
    by_time: dict[int, dict[str, Any]] = {}
    cursor = start
    while cursor < end:
        chunk_end = min(end, cursor + chunk_seconds)
        for row in client.candles(symbol, cursor, chunk_end):
            timestamp = int(row["time"])
            if start <= timestamp < end:
                by_time[timestamp] = row
        cursor = chunk_end
        time.sleep(0.05)

    coverage_tolerance = 24 * 60 * 60 if symbol.startswith("FUNDING:") else 60 * 60
    _validate_underlying_coverage(
        by_time,
        start,
        end,
        tolerance_seconds=coverage_tolerance,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for timestamp in sorted(by_time):
            row = by_time[timestamp]
            # Delta timestamps candles by candle-open; the normalized contract
            # Timestamp bars by close so the engine can reject incomplete bars.
            writer.writerow([
                _iso_utc(timestamp + 300),
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row.get("volume", 0),
            ])
    temporary.replace(output)
    return len(by_time)


def _validate_underlying_coverage(
    by_time: dict[int, dict[str, Any]],
    start: int,
    end: int,
    *,
    tolerance_seconds: int = 60 * 60,
) -> None:
    """Reject silently truncated long-range five-minute history."""
    if end - start <= 60 * 60:
        return
    if not by_time:
        raise RuntimeError("Delta returned no candles for the requested range")

    timestamps = sorted(by_time)
    if timestamps[0] - start > tolerance_seconds:
        raise RuntimeError(
            "Delta candle history is missing the beginning of the requested range"
        )
    if end - timestamps[-1] > tolerance_seconds:
        raise RuntimeError(
            "Delta candle history is missing the end of the requested range"
        )

    largest_gap = max(
        (current - previous for previous, current in zip(timestamps, timestamps[1:])),
        default=0,
    )
    if largest_gap > tolerance_seconds:
        raise RuntimeError(
            "Delta candle history contains an internal gap of "
            f"{largest_gap // 60} minutes"
        )


def download_option_products(client: DeltaPublicClient, output: Path) -> int:
    products = list(client.products(
        contract_types="call_options,put_options",
        states="upcoming,live,expired,settled",
    ))
    products.sort(key=lambda item: (str(item.get("settlement_time") or ""), str(item.get("symbol") or "")))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "source": "delta_india_public_api",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "count": len(products),
        "products": products,
    }, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return len(products)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_rows(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def _days(start: int, end: int) -> Iterator[date]:
    current = datetime.fromtimestamp(start, UTC).date()
    last = datetime.fromtimestamp(max(start, end - 1), UTC).date()
    while current <= last:
        yield current
        current += timedelta(days=1)


def _day_bounds(day: date) -> tuple[int, int]:
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    return start, start + 86_400


def _safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol)


def _cached_candles(
    client: DeltaPublicClient,
    cache: Path,
    symbol: str,
    resolution: str,
    day: date,
    refresh: bool,
) -> tuple[list[dict[str, Any]], bool]:
    path = cache / "candles" / resolution / _safe_symbol(symbol) / f"{day.isoformat()}.json"
    if path.is_file() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("rows") or []), False
    start, end = _day_bounds(day)
    rows = [
        row for row in client.candles(symbol, start, end, resolution=resolution)
        if start <= int(row["time"]) < end
    ]
    _atomic_json(path, {
        "source": "delta_india_public_api",
        "symbol": symbol,
        "resolution": resolution,
        "date": day.isoformat(),
        "rows": rows,
    })
    return rows, True


def _cached_products(
    client: DeltaPublicClient,
    cache: Path,
    expiry: date,
    refresh: bool,
) -> tuple[list[dict[str, Any]], bool]:
    path = cache / "products" / f"BTC-{expiry.isoformat()}.json"
    if path.is_file() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("products") or []), False
    products = list(client.products(
        "call_options,put_options",
        "upcoming,live,expired,settled",
        expiry=expiry.isoformat(),
        underlying_asset_symbols="BTC",
    ))
    products = [
        item for item in products
        if (item.get("underlying_asset") or {}).get("symbol") == "BTC"
    ]
    _atomic_json(path, {
        "source": "delta_india_public_api",
        "expiry": expiry.isoformat(),
        "products": products,
    })
    return products, True


def _precision(increment: float) -> int:
    text = f"{increment:.12f}".rstrip("0")
    return len(text.partition(".")[2])


def _normalized_option_symbol(product: dict[str, Any]) -> str:
    source = str(product["symbol"]).upper()
    suffix = "CE" if product.get("contract_type") == "call_options" else "PE"
    core = re.sub(r"[^A-Z0-9]", "", source[2:])
    return f"{core}{suffix}"


def _nearest_strikes(products: list[dict[str, Any]], prices: list[float], count: int) -> set[float]:
    strikes = sorted({float(item["strike_price"]) for item in products})
    selected: set[float] = set()
    for price in prices:
        selected.update(sorted(strikes, key=lambda strike: abs(strike - price))[:count])
    return selected


def sync_historical_dataset(
    client: DeltaPublicClient,
    output: Path,
    *,
    start: int,
    end: int,
    warmup_bars: int,
    candle_seconds: int,
    option_resolution: str,
    estimated_spread_percent: float,
    expiry_horizon_days: int,
    strikes_around_atm: int,
    min_days_to_expiry: int,
    allow_same_day_expiry: bool,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Build an offline Delta dataset, caching each public daily response."""
    if end <= start:
        raise ValueError("end must be later than start")
    if option_resolution != "1m":
        raise ValueError("only 1m option history is currently supported")

    cache = output / "raw"
    warmup_start = start - warmup_bars * candle_seconds
    downloaded_requests = 0
    reused_requests = 0

    def account_request(label: str, downloaded: bool) -> None:
        nonlocal downloaded_requests, reused_requests
        downloaded_requests += int(downloaded)
        reused_requests += int(not downloaded)
        if progress and downloaded:
            progress(f"[downloaded] {label}")

    underlying_rows: dict[int, dict[str, Any]] = {}
    for day in _days(warmup_start, end):
        rows, downloaded = _cached_candles(client, cache, "BTCUSD", "5m", day, refresh)
        account_request(f"BTCUSD 5m {day.isoformat()}", downloaded)
        for row in rows:
            timestamp = int(row["time"])
            if warmup_start <= timestamp < end:
                underlying_rows[timestamp] = row
    if not underlying_rows:
        raise RuntimeError("Delta returned no BTCUSD candles for the configured period")

    ist = timezone(timedelta(hours=5, minutes=30))
    first_market_day = datetime.fromtimestamp(start, ist).date()
    last_market_day = datetime.fromtimestamp(end - 1, ist).date()
    minimum_days = 0 if allow_same_day_expiry else max(1, min_days_to_expiry)
    expiry_day = first_market_day + timedelta(days=minimum_days)
    last_expiry_day = last_market_day + timedelta(days=expiry_horizon_days)
    products: list[dict[str, Any]] = []
    while expiry_day <= last_expiry_day:
        rows, downloaded = _cached_products(client, cache, expiry_day, refresh)
        account_request(f"BTC option products expiring {expiry_day.isoformat()}", downloaded)
        products.extend(rows)
        expiry_day += timedelta(days=1)

    active_products: list[dict[str, Any]] = []
    option_start = start - max(60, candle_seconds)
    for product in products:
        try:
            activation = _parse_utc(str(product.get("launch_time") or product.get("created_at")))
            expiration = _parse_utc(str(product["settlement_time"]))
            strike = float(product["strike_price"])
            contract_value = float(product["contract_value"])
            tick_size = float(product["tick_size"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            activation.timestamp() < end
            and expiration.timestamp() > option_start
            and strike > 0
            and contract_value > 0
            and tick_size > 0
        ):
            active_products.append(product)

    selected_products: list[dict[str, Any]] = []
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for product in active_products:
        expiry_key = str(product.get("settlement_time"))
        by_expiry.setdefault(expiry_key, []).append(product)

    expiry_dates = sorted(
        (_parse_utc(expiry_key).date(), expiry_key) for expiry_key in by_expiry
    )
    prices_by_expiry: dict[str, list[float]] = {}
    first_selection_by_expiry: dict[str, int] = {}
    for timestamp, row in sorted(underlying_rows.items()):
        if not start <= timestamp < end:
            continue
        price = float(row["close"])
        if price <= 0:
            continue
        market_day = datetime.fromtimestamp(timestamp, ist).date()
        eligible = next(
            (
                expiry_key
                for expiry_date, expiry_key in expiry_dates
                if (expiry_date - market_day).days >= minimum_days
            ),
            None,
        )
        if eligible is None:
            continue
        prices_by_expiry.setdefault(eligible, []).append(price)
        first_selection_by_expiry.setdefault(eligible, timestamp)
    if not prices_by_expiry:
        raise RuntimeError("Delta returned no tradable BTCUSD candles with an eligible option expiry")

    for expiry_key, trade_prices in prices_by_expiry.items():
        group = by_expiry[expiry_key]
        selected = _nearest_strikes(group, trade_prices, strikes_around_atm)
        selected_products.extend(item for item in group if float(item["strike_price"]) in selected)

    instruments: list[list[Any]] = []
    quotes: list[list[Any]] = []
    for product in sorted(selected_products, key=lambda item: str(item["symbol"])):
        source_symbol = str(product["symbol"])
        symbol = _normalized_option_symbol(product)
        activation = _parse_utc(str(product.get("launch_time") or product.get("created_at")))
        expiration = _parse_utc(str(product["settlement_time"]))
        tick_size = float(product["tick_size"])
        option_rows: list[dict[str, Any]] = []
        oi_rows: list[dict[str, Any]] = []
        expiry_key = str(product.get("settlement_time"))
        first_selection = first_selection_by_expiry[expiry_key]
        fetch_start = max(first_selection - 60, int(activation.timestamp()))
        fetch_end = min(end, int(expiration.timestamp()))
        if fetch_end <= fetch_start:
            continue
        requests = [
            (requested_symbol, day, is_oi)
            for day in _days(fetch_start, fetch_end)
            for requested_symbol, is_oi in (
                (source_symbol, False),
                (f"OI:{source_symbol}", True),
            )
        ]
        with ThreadPoolExecutor(max_workers=min(4, len(requests))) as executor:
            futures = {
                executor.submit(
                    _cached_candles,
                    client,
                    cache,
                    requested_symbol,
                    option_resolution,
                    day,
                    refresh,
                ): (requested_symbol, day, is_oi)
                for requested_symbol, day, is_oi in requests
            }
            for future in as_completed(futures):
                requested_symbol, day, is_oi = futures[future]
                rows, downloaded = future.result()
                account_request(
                    f"{requested_symbol} {option_resolution} {day.isoformat()}",
                    downloaded,
                )
                (oi_rows if is_oi else option_rows).extend(rows)
        option_rows.sort(key=lambda row: int(row["time"]))
        oi_by_time = sorted(
            (int(row["time"]), float(row["close"]))
            for row in oi_rows
            if row.get("close") not in {None, ""}
        )
        oi_times = [item[0] for item in oi_by_time]
        cumulative_volume: dict[date, float] = {}
        product_quote_count = 0
        half_spread = estimated_spread_percent / 200.0
        for row in option_rows:
            open_time = int(row["time"])
            quote_time = open_time + 60
            if not option_start <= quote_time < end:
                continue
            midpoint = float(row["close"])
            if not math.isfinite(midpoint) or midpoint <= 0:
                continue
            day = datetime.fromtimestamp(open_time, UTC).date()
            candle_volume = max(0.0, float(row.get("volume") or 0.0))
            cumulative_volume[day] = cumulative_volume.get(day, 0.0) + candle_volume
            bid = math.floor(midpoint * (1.0 - half_spread) / tick_size) * tick_size
            ask = math.ceil(midpoint * (1.0 + half_spread) / tick_size) * tick_size
            bid = max(tick_size, bid)
            ask = max(bid + tick_size, ask)
            oi_index = bisect.bisect_right(oi_times, open_time) - 1
            oi = oi_by_time[oi_index][1] if oi_index >= 0 else ""
            estimated_size = max(1.0, candle_volume)
            quotes.append([
                _iso_utc(quote_time), symbol, f"{bid:.{_precision(tick_size)}f}",
                f"{ask:.{_precision(tick_size)}f}", estimated_size, estimated_size,
                cumulative_volume[day], oi,
            ])
            product_quote_count += 1
        if not product_quote_count:
            continue
        expiry = expiration.strftime("%d%b%y").upper()
        instruments.append([
            symbol, source_symbol, expiry, product["strike_price"],
            "CE" if product.get("contract_type") == "call_options" else "PE",
            activation.isoformat().replace("+00:00", "Z"),
            expiration.isoformat().replace("+00:00", "Z"),
            _precision(tick_size), 0, tick_size, 1, 1, 1, product["contract_value"],
        ])

    if not instruments or not quotes:
        raise RuntimeError("Delta returned no usable option candles for the configured period")
    bars = [
        [
            _iso_utc(timestamp + candle_seconds), row["open"], row["high"],
            row["low"], row["close"], row.get("volume", 0),
        ]
        for timestamp, row in sorted(underlying_rows.items())
    ]
    quotes.sort(key=lambda row: (row[0], row[1]))
    _atomic_rows(
        output / "underlying_bars.csv",
        ["timestamp", "open", "high", "low", "close", "volume"],
        bars,
    )
    _atomic_rows(
        output / "option_instruments.csv",
        [
            "symbol", "source_symbol", "expiry", "strike", "option_type", "activation", "expiration",
            "price_precision", "size_precision", "price_increment", "size_increment", "lot_size",
            "min_quantity", "contract_value",
        ],
        instruments,
    )
    _atomic_rows(
        output / "option_quotes.csv",
        ["timestamp", "symbol", "bid", "ask", "bid_size", "ask_size", "volume", "open_interest"],
        quotes,
    )
    return {
        "underlying_bars": len(bars),
        "option_instruments": len(instruments),
        "option_quotes": len(quotes),
        "downloaded_requests": downloaded_requests,
        "reused_cached_requests": reused_requests,
        "estimated_spread_percent": estimated_spread_percent,
        "fidelity": "LOW_FIDELITY",
    }
