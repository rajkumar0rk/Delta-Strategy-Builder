"""Offline persistence and restart guarantees for opt-in research job metadata."""
import json
import time
from uuid import uuid4

from app.job_persistence import JobStateStore
from app.jobs import JobManager


def _wait_until_done(manager, jid, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(jid)
        if record["status"] in {"COMPLETE", "FAILED", "CANCELLED"}:
            return record
        time.sleep(0.01)
    raise AssertionError("job did not reach terminal state")


def test_completed_jobs_survive_manager_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("STRATEGY_LAB_JOB_STATE_DIR", str(tmp_path))
    manager = JobManager()
    jid = manager.create(lambda progress: {"value": 42})
    original = _wait_until_done(manager, jid)
    assert original["status"] == "COMPLETE"
    assert original["result"] == {"value": 42}
    restarted = JobManager()
    assert restarted.get(jid)["status"] == "COMPLETE"
    assert restarted.get(jid)["result"] == {"value": 42}
    manager._pool.shutdown(wait=True)
    restarted._pool.shutdown(wait=True)


def test_incomplete_snapshots_are_marked_interrupted(tmp_path):
    store = JobStateStore(tmp_path)
    jid = uuid4().hex
    store.save(jid, {
        "id": jid, "status": "RUNNING", "stage": "BACKTEST",
        "events": [], "cancel_requested": False, "result": {"unsafe": True},
    })
    loaded = store.load()[jid]
    assert loaded["status"] == "FAILED"
    assert loaded["stage"] == "INTERRUPTED"
    assert loaded["error"] == "JOB_INTERRUPTED_BY_RESTART"
    assert loaded["result"] is None
    assert store.load()[jid]["status"] == "FAILED"


def test_atomic_state_file_cleanup_and_unknown_formats(tmp_path):
    store = JobStateStore(tmp_path)
    jid = uuid4().hex
    store.save(jid, {"id": jid, "status": "COMPLETE", "result": {"done": True}})
    assert store.load()[jid]["result"] == {"done": True}
    assert not list(tmp_path.glob("*.tmp"))
    (tmp_path / (uuid4().hex + ".json")).write_text("{broken", encoding="utf-8")
    assert len(store.load()) == 1
    store.delete(jid)
    assert jid not in store.load()
