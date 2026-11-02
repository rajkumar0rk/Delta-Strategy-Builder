from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Lock
from uuid import uuid4
from typing import Any, Callable

from .job_persistence import JobStateStore


class JobCancelled(RuntimeError):
    """Cooperative cancellation raised at engine progress checkpoints."""


class JobManager:
    def __init__(self):
        directory = os.getenv("STRATEGY_LAB_JOB_STATE_DIR", "").strip()
        self._state_store = JobStateStore(directory) if directory else None
        self._jobs: dict[str, dict[str, Any]] = (
            self._state_store.load() if self._state_store is not None else {}
        )
        self._lock = Lock()
        self.max_workers=max(1,min(16,int(os.getenv('STRATEGY_LAB_MAX_WORKERS','2'))))
        self.max_pending=max(1,min(1000,int(os.getenv('STRATEGY_LAB_MAX_PENDING_JOBS','8'))))
        self.max_retained=max(10,min(10000,int(os.getenv('STRATEGY_LAB_MAX_RETAINED_JOBS','200'))))
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers)

    def _save_locked(self, jid: str) -> None:
        if self._state_store is not None:
            self._state_store.save(jid, self._jobs[jid])

    def _delete_locked(self, jid: str) -> None:
        if self._state_store is not None:
            self._state_store.delete(jid)


    def _cancel_requested(self, jid: str) -> bool:
        with self._lock:
            return bool(self._jobs.get(jid, {}).get('cancel_requested'))

    def create(self, fn: Callable[[Callable[..., None]], Any]) -> str:
        jid = uuid4().hex
        with self._lock:
            # Evict only terminal job records; active progress/cancellation
            # state is never removed. Results are still on disk.
            finished=[key for key,record in self._jobs.items()
                      if record['status'] in {'COMPLETE','FAILED','CANCELLED'}]
            for key in finished[:max(0,len(self._jobs)-self.max_retained+1)]:
                del self._jobs[key]
                self._delete_locked(key)
            active=sum(j['status'] in {'QUEUED','RUNNING','CANCELLING'} for j in self._jobs.values())
            if active>=self.max_workers+self.max_pending:
                raise RuntimeError('JOB_QUEUE_FULL: adjust STRATEGY_LAB_MAX_PENDING_JOBS or retry after active work completes')
            self._jobs[jid] = {
                'id': jid,
                'status': 'QUEUED',
                'message': 'Queued',
                'stage': 'QUEUED',
                'progress_percent': 0.0,
                'next_step': 'Start',
                'events': [],
                'result': None,
                'error': None,
                'cancel_requested': False,
            }
            self._save_locked(jid)

        def progress(message: str, percent: float | None = None, stage: str | None = None, next_step: str | None = None):
            # The engine already reports at expensive stage boundaries, quote-index
            # checkpoints and during the candle loop. Reuse those same checkpoints
            # as cooperative cancellation points so no unsafe thread termination is
            # needed and partially-written result files are never exposed as complete.
            with self._lock:
                job = self._jobs[jid]
                if job.get('cancel_requested'):
                    raise JobCancelled('Backtest stopped by user')
                old_stage = job['stage']
                job['message'] = str(message)
                if percent is not None:
                    job['progress_percent'] = max(0.0, min(100.0, float(percent)))
                if stage:
                    job['stage'] = str(stage)
                if next_step is not None:
                    job['next_step'] = str(next_step)
                event = {
                    'message': str(message),
                    'percent': job['progress_percent'],
                    'stage': job['stage'],
                    'next_step': job['next_step'],
                }
                events = job.setdefault('events', [])
                if not events or events[-1]['message'] != event['message']:
                    events.append(event)
                    if len(events) > 50:
                        del events[:-50]
                # Persist stage transitions, not every candle progress update.
                if job['stage'] != old_stage:
                    self._save_locked(jid)

        def work():
            with self._lock:
                job = self._jobs[jid]
                if job.get('cancel_requested'):
                    job.update(status='CANCELLED', stage='CANCELLED', message='Stopped before start', next_step='')
                    self._save_locked(jid)
                    return
                job.update(status='RUNNING', stage='STARTING', message='Starting backtest…', progress_percent=1.0)
                self._save_locked(jid)
            try:
                result = fn(progress)
                with self._lock:
                    job = self._jobs[jid]
                    if job.get('cancel_requested'):
                        job.update(status='CANCELLED', message='Backtest stopped', stage='CANCELLED', next_step='', result=None)
                    else:
                        job.update(
                            status='COMPLETE', message='Complete', stage='COMPLETE',
                            progress_percent=100.0, next_step='', result=result,
                        )
                    self._save_locked(jid)
            except JobCancelled as exc:
                with self._lock:
                    self._jobs[jid].update(
                        status='CANCELLED', message=str(exc), stage='CANCELLED', next_step='',
                        error=None, result=None,
                    )
                    self._save_locked(jid)
            except Exception as exc:
                with self._lock:
                    self._jobs[jid].update(
                        status='FAILED', message=str(exc), stage='FAILED', next_step='',
                        error=f'{type(exc).__name__}: {exc}',
                    )
                    self._save_locked(jid)

        self._pool.submit(work)
        return jid

    def cancel(self, jid: str) -> dict[str, Any]:
        with self._lock:
            if jid not in self._jobs:
                raise KeyError(jid)
            job = self._jobs[jid]
            if job['status'] in {'COMPLETE', 'FAILED', 'CANCELLED'}:
                return dict(job)
            job['cancel_requested'] = True
            job['status'] = 'CANCELLING'
            job['stage'] = 'CANCELLING'
            job['message'] = 'Stop requested — finishing the current safe checkpoint…'
            job['next_step'] = 'Cancel safely'
            self._save_locked(jid)
            return dict(job)

    def get(self, jid: str) -> dict[str, Any]:
        with self._lock:
            if jid not in self._jobs:
                raise KeyError(jid)
            job = dict(self._jobs[jid])
            job['events'] = list(job.get('events', []))
            return job


jobs = JobManager()
