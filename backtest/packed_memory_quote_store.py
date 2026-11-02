"""Optional packed in-memory captured quotes for the legacy H6 research runner.

Store each of the seven normalized double-valued fields in a contiguous,
little-endian 56-byte record. This avoids retaining a Python dict for every
captured quote, while reconstructing exactly the original float values on
demand. No quantization, NaN replacement, or timestamps rounded to int.
This is *not* streaming signal generation or a bound on total process RAM.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
import struct

_KEYS = (
    "timestamp_ns", "bid", "ask", "bid_size", "ask_size", "volume",
    "open_interest",
)
_PACKER = struct.Struct("<7d")


class PackedQuoteView(Sequence):
    def __init__(self, store: "PackedMemoryQuoteStore", event_id: int):
        self._store = store
        self._event_id = event_id

    def __len__(self) -> int:
        return len(self._store._buffers.get(self._event_id, ())) // _PACKER.size

    def _item(self, index: int) -> dict[str, float]:
        data = self._store._buffers.get(self._event_id)
        if data is None:
            raise IndexError(index)
        count = len(data) // _PACKER.size
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError(index)
        return dict(zip(
            _KEYS, _PACKER.unpack_from(data, index * _PACKER.size)
        ))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self._item(i) for i in range(*index.indices(len(self))))
        if not isinstance(index, int):
            raise TypeError("Quote indexes must be integers or slices")
        return self._item(index)

    def __iter__(self) -> Iterator[dict[str, float]]:
        for index in range(len(self)):
            yield self._item(index)

    def __reversed__(self) -> Iterator[dict[str, float]]:
        for index in range(len(self) - 1, -1, -1):
            yield self._item(index)


class PackedMemoryQuoteStore:
    def __init__(self, *, max_captured: int | None = None):
        if max_captured is not None and max_captured < 1:
            raise ValueError("max_captured must be positive")
        self._buffers: dict[int, bytearray] = {}
        self._max_captured = max_captured
        self._total = 0
        self._closed = False

    def view(self, event_id: int) -> PackedQuoteView:
        if self._closed:
            raise RuntimeError("Packed quote store closed")
        return PackedQuoteView(self, event_id)

    def append(self, event_id: int, quote: dict[str, float]) -> None:
        if self._closed:
            raise RuntimeError("Packed quote store closed")
        if self._max_captured is not None and self._total >= self._max_captured:
            raise ValueError("CAPTURED_QUOTE_LIMIT_EXCEEDED")
        if set(quote) != set(_KEYS):
            raise ValueError("PACKED_QUOTE_SCHEMA_MISMATCH")
        payload = _PACKER.pack(*(quote[name] for name in _KEYS))
        self._buffers.setdefault(event_id, bytearray()).extend(payload)
        self._total += 1

    def flush(self) -> None:
        if self._closed:
            raise RuntimeError("Packed quote store closed")

    def snapshot_metrics(self) -> dict[str, int | str]:
        if self._closed:
            raise RuntimeError("Packed quote store closed")
        return {
            "payload_encoding": "PACKED_MEMORY",
            "captured_quote_rows": self._total,
            "event_count": len(self._buffers),
            "packed_payload_bytes": sum(len(x) for x in self._buffers.values()),
        }

    @property
    def total(self) -> int:
        return self._total

    def close(self) -> None:
        if not self._closed:
            self._buffers.clear()
            self._closed = True
