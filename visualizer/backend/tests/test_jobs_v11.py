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
