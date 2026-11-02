"""Opt-in, lossless JSONL spool for the legacy research report collections.

This is a separate output API. The ordinary run_dataset return contract is
unchanged. With a spool, aggregate trades, attempts, and decisions are written
as they arrive; per-scenario trade collections and the indicator/signal/quote
pipeline still require memory. A canonical JSON report is assembled by
streaming raw JSONL rows rather than loading them into another Python list.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


_FIELDS = ("trades", "execution_attempts", "decision_events")


class JsonlRecords:
    def __init__(self, path: Path):
        self.path = path
        self._file = path.open("w", encoding="utf-8", newline="\n")
        self._count = 0
        self._closed = False

    def append(self, record: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("REPORT_SPOOL_CLOSED")
        self._file.write(json.dumps(
            record, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
        ) + "\n")
        self._count += 1

    def extend(self, records: Iterable[dict[str, Any]]) -> None:
        for record in records:
            self.append(record)

    def __len__(self) -> int:
        return self._count

    def _flush(self) -> None:
        if not self._closed:
            self._file.flush()

    def iter_json_lines(self):
        self._flush()
        with self.path.open("r", encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    yield line.rstrip("\n")

    def __iter__(self):
        for line in self.iter_json_lines():
            yield json.loads(line)

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True


class StreamedReportRecords:
    """Own three independent append-only spools and an atomic output writer."""

    def __init__(self, *, spool_directory: Path | None = None):
        if spool_directory is not None:
            Path(spool_directory).mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="legacy-records-", dir=spool_directory,
        )
        root = Path(self._temp.name)
        self._sinks = {
            name: JsonlRecords(root / f"{name}.jsonl")
            for name in _FIELDS
        }
        self._closed = False

    def sink(self, name: str) -> JsonlRecords:
        if self._closed:
            raise RuntimeError("REPORT_SPOOL_CLOSED")
        return self._sinks[name]

    def write_report(self, report: dict[str, Any], output: Path) -> dict[str, Any]:
        """Write complete original report shape without materializing spool rows.

        Only files under a temporary directory are used for intermediate
        records. The destination is replaced atomically *after* a complete
        successful serialization; any existing destination survives failure.
        """
        if self._closed:
            raise RuntimeError("REPORT_SPOOL_CLOSED")
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=output.parent, prefix=f".{output.name}.",
                suffix=".partial", delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write("{")
                for index, (name, value) in enumerate(report.items()):
                    if index:
                        stream.write(",")
                    stream.write(json.dumps(name))
                    stream.write(":")
                    if name in _FIELDS:
                        expected = self.sink(name)
                        if value is not expected:
                            raise ValueError("REPORT_SPOOL_FIELD_MISMATCH")
                        stream.write("[")
                        for number, item in enumerate(expected.iter_json_lines()):
                            if number:
                                stream.write(",")
                            stream.write(item)
                        stream.write("]")
                    else:
                        json.dump(value, stream, allow_nan=False)
                stream.write("}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, output)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {
            "report_path": str(output),
            "report_bytes": output.stat().st_size,
            "counts": {name: len(self.sink(name)) for name in _FIELDS},
        }

    def write_csv_exports(self, directory: Path) -> dict[str, str]:
        """Write legacy CSV exports from JSONL without materializing rows.

        Match the historical writer's header semantics: trade keys follow
        the first trade, whereas attempts/decisions use first-seen key order
        across all records. Each CSV is published atomically. Existing files
        are preserved if a specific CSV fails to serialize.
        """
        if self._closed:
            raise RuntimeError("REPORT_SPOOL_CLOSED")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        output_paths: dict[str, str] = {}
        for field in _FIELDS:
            sink = self.sink(field)
            if not len(sink):
                continue
            if field == "trades":
                first = next(iter(sink))
                fieldnames = list(first)
            else:
                fieldnames = list(dict.fromkeys(
                    key for record in sink for key in record
                ))
            output = directory / f"{field}.csv"
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="",
                    dir=directory, prefix=f".{field}.",
                    suffix=".partial", delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(iter(sink))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, output)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            output_paths[field] = str(output)
        return output_paths

    def close(self) -> None:
        if self._closed:
            return
        try:
            for sink in self._sinks.values():
                sink.close()
        finally:
            self._temp.cleanup()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
