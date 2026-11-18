import time

from app.jobs import JobManager


def test_job_can_be_cancelled_cooperatively():
    manager = JobManager()

    def work(progress):
        for i in range(500):
            progress(f'step {i}', i / 5, 'BACKTEST_LOOP', 'continue')
            time.sleep(0.002)
        return {'ok': True}

    jid = manager.create(work)
    deadline = time.time() + 2
    while time.time() < deadline:
        state = manager.get(jid)
        if state['status'] == 'RUNNING':
            break
        time.sleep(0.005)
    manager.cancel(jid)
    deadline = time.time() + 2
    while time.time() < deadline:
        state = manager.get(jid)
        if state['status'] == 'CANCELLED':
            break
        time.sleep(0.005)
    assert state['status'] == 'CANCELLED'
    assert state['result'] is None
    assert state['error'] is None


def test_finished_jobs_are_bounded_in_memory():
    manager = JobManager()
    ids = [manager.create(lambda progress: {'ok': True}) for _ in range(11)]
    deadline = time.time() + 4
    while time.time() < deadline:
        with manager._lock:
            all_finished = ids[-1] in manager._jobs and manager._jobs[ids[-1]]['status'] == 'COMPLETE'
        if all_finished:
            break
        time.sleep(0.01)
    with manager._lock:
        assert len(manager._finished) == manager._max_finished
        assert len(manager._jobs) <= manager._max_finished
        assert ids[-1] in manager._jobs
