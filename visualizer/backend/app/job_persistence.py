"""Optional atomic JSON snapshots for in-process research job *metadata*.

Snapshots never restart work or execute serialized callables. On process
restart, incomplete jobs are explicitly marked FAILED/INTERRUPTED instead
of incorrectly appearing queued forever. Enable with STRATEGY_LAB_JOB_STATE_DIR.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


_TERMINAL = {"COMPLETE", "FAILED", "CANCELLED"}
_INTERRUPTED = {"QUEUED", "RUNNING", "CANCELLING"}


class JobStateStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        # JobManager issues 32-character hexadecimal uuid4 IDs.
        if len(job_id) != 32 or any(ch not in "0123456789abcdef" for ch in job_id):
            raise ValueError("invalid job id")
        return self.directory / f"{job_id}.json"

    def save(self, job_id: str, record: dict[str, Any]) -> None:
        target = self._path(job_id)
        # Results are API-JSON-shaped in the normal app. Explicitly serialize
        # non-JSON scalar values as strings rather than storing pickles/code.
        payload = json.dumps(record, default=str, allow_nan=False, sort_keys=True)
        fd, name = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def delete(self, job_id: str) -> None:
        self._path(job_id).unlink(missing_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for path in sorted(self.directory.glob("*.json")):
            jid = path.stem
            try:
                if self._path(jid) != path:
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or record.get("id") != jid:
                    continue
                if record.get("status") not in _TERMINAL | _INTERRUPTED:
                    continue
                record["events"] = record.get("events", [])[-50:]
                if record["status"] in _INTERRUPTED:
                    record.update(
                        status="FAILED",
                        stage="INTERRUPTED",
                        message="Interrupted by application restart",
                        next_step="Start a new backtest",
                        error="JOB_INTERRUPTED_BY_RESTART",
                        cancel_requested=False,
                        result=None,
                    )
                    self.save(jid, record)
                records[jid] = record
            except (OSError, ValueError, TypeError, KeyError):
                # Corrupt snapshots are ignored; never execute or unpickle.
                continue
        return records
