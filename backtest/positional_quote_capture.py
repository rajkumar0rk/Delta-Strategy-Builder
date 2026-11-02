"""Opt-in positional parsing of normalized historical option quote CSVs.

The original csv.DictReader paths remain the default and act as an
independent regression oracle. Resolve the header once, avoiding a Python
dictionary per CSV row. Event ordering, inclusive expiry windows and quote
payloads intentionally match the original capture routines.
"""
from __future__ import annotations

import csv
import heapq
from collections import defaultdict
from pathlib import Path
from typing import Any

from .data import timestamp_ns

NS_MINUTE = 60 * 1_000_000_000


def _quote_rows(path: Path):
    """Yield raw CSV records with positions resolved once, not per row."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return
        columns = {name: i for i, name in enumerate(header)}
        # Same required fields as the original capture path. Optional quote
        # sizes/volume may be absent or have blank values.
        for name in ("symbol", "timestamp", "bid", "ask"):
            if name not in columns:
                raise KeyError(name)
        symbol_index = columns["symbol"]
        for row in reader:
            symbol = row[symbol_index] if symbol_index < len(row) else None
            yield symbol, row, columns


def _required(row: list[str], columns: dict[str, int], key: str):
    index = columns[key]
    return row[index] if index < len(row) else None


def _optional(row: list[str], columns: dict[str, int], key: str):
    index = columns.get(key)
    if index is None or index >= len(row):
        return None
    return row[index]


def _payload(row: list[str], columns: dict[str, int], current_ns: int):
    return {
        "timestamp_ns": float(current_ns),
        "bid": float(_required(row, columns, "bid")),
        "ask": float(_required(row, columns, "ask")),
        "bid_size": float(_optional(row, columns, "bid_size") or 0.0),
        "ask_size": float(_optional(row, columns, "ask_size") or 0.0),
        "volume": float(_optional(row, columns, "volume") or 0.0),
        "open_interest": float(_optional(row, columns, "open_interest") or 0.0),
    }


def capture_quotes_positional(
    path: Path, events: list[Any], horizon_minutes: float | None = 65, *,
    quote_store=None,
) -> None:
    by_symbol: dict[str, list[Any]] = {}
    for event in events:
        if quote_store is not None:
            event.quotes = quote_store.view(id(event))
        by_symbol.setdefault(event.option.symbol, []).append(event)
    for selected in by_symbol.values():
        selected.sort(key=lambda item: item.timestamp_ns)
    horizon_ns = int(horizon_minutes * NS_MINUTE) if horizon_minutes is not None else None
    for symbol, row, columns in _quote_rows(path):
        selected = by_symbol.get(symbol)
        if not selected:
            continue
        current_ns = timestamp_ns(_required(row, columns, "timestamp"))
        quote = _payload(row, columns, current_ns)
        for event in selected:
            end_ns = (
                event.timestamp_ns + horizon_ns
                if horizon_ns is not None else event.option.expiration_ns
            )
            end_ns = min(end_ns, event.option.expiration_ns)
            if event.timestamp_ns < current_ns <= end_ns:
                if quote_store is not None:
                    quote_store.append(id(event), quote)
                else:
                    event.quotes.append(quote)
    if quote_store is not None:
        quote_store.flush()


def capture_quotes_sweep_positional(
    path: Path, events: list[Any], horizon_minutes: float | None = 65, *,
    quote_store=None,
    max_active_events: int | None = None,
) -> None:
    if max_active_events is not None and max_active_events < 1:
        raise ValueError("max_active_events must be positive")
    horizon_ns = int(horizon_minutes * NS_MINUTE) if horizon_minutes is not None else None
    scheduled = defaultdict(list)
    for event in events:
        if quote_store is not None:
            event.quotes = quote_store.view(id(event))
        scheduled[event.option.symbol].append(event)
    for group in scheduled.values():
        group.sort(key=lambda e: e.timestamp_ns)
    next_index = defaultdict(int)
    active = defaultdict(dict)
    expiry_heap = defaultdict(list)
    previous_ns = None
    for symbol, row, columns in _quote_rows(path):
        # SWEEP checks monotonic time even when no symbols are selected.
        current_ns = timestamp_ns(_required(row, columns, "timestamp"))
        if previous_ns is not None and current_ns < previous_ns:
            raise ValueError("QUOTE_TIMESTAMP_OUT_OF_ORDER")
        previous_ns = current_ns
        group = scheduled.get(symbol)
        if not group:
            continue
        index = next_index[symbol]
        while index < len(group) and group[index].timestamp_ns < current_ns:
            event = group[index]
            end_ns = min(
                event.timestamp_ns + horizon_ns
                if horizon_ns is not None else event.option.expiration_ns,
                event.option.expiration_ns,
            )
            if end_ns >= current_ns:
                identity = id(event)
                active[symbol][identity] = event
                heapq.heappush(expiry_heap[symbol], (end_ns, identity))
                if max_active_events is not None and len(active[symbol]) > max_active_events:
                    raise ValueError("ACTIVE_EVENT_LIMIT_EXCEEDED")
            index += 1
        next_index[symbol] = index
        while expiry_heap[symbol] and expiry_heap[symbol][0][0] < current_ns:
            _, identity = heapq.heappop(expiry_heap[symbol])
            active[symbol].pop(identity, None)
        if not active[symbol]:
            continue
        quote = _payload(row, columns, current_ns)
        for event in active[symbol].values():
            if quote_store is not None:
                quote_store.append(id(event), quote)
            else:
                event.quotes.append(quote)
    if quote_store is not None:
        quote_store.flush()
