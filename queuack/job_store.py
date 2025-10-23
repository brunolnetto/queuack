# file: job_models.py

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from .data_models import Job
from .status import JobStatus


class JobStore(Protocol):
    """Minimal interface the DAG engine uses to persist job state.

    Implementations should be lightweight adapters around the real
    persistence layer (e.g. DuckQueue) or an in-memory fake for tests.
    """

    def get_job(self, job_id: str): ...

    def update_job_status(
        self,
        job_id: str,
        *,
        status: Optional[object] = None,
        skipped_at: Optional[datetime] = None,
        skip_reason: Optional[str] = None,
        skipped_by: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> None: ...

    def bulk_update(self, updates: Iterable[Dict[str, Any]]) -> None:
        """Apply multiple updates. Each item is a dict with 'id' and keyword args for update_job_status."""
        ...


class InMemoryJobStore:
    """Simple in-memory JobStore useful for unit tests.

    Stores Job objects keyed by id. update_job_status mutates the stored
    Job instance fields.
    """

    def __init__(self, jobs: Optional[Iterable[Job]] = None):
        self._jobs: Dict[str, Job] = {}
        if jobs:
            for j in jobs:
                self._jobs[j.id] = j

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update_job_status(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        skipped_at: Optional[datetime] = None,
        skip_reason: Optional[str] = None,
        skipped_by: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return

        if status is not None:
            job.status = status.value if isinstance(status, JobStatus) else status

        if skipped_at is not None:
            job.skipped_at = skipped_at
        if skip_reason is not None:
            job.skip_reason = skip_reason
        if skipped_by is not None:
            job.skipped_by = skipped_by
        if attempts is not None:
            job.attempts = attempts

    def bulk_update(self, updates: Iterable[Dict[str, Any]]) -> None:
        for upd in updates:
            job_id = upd.pop("id")
            self.update_job_status(job_id, **upd)


class DuckQueueAdapter(JobStore):
    """Thin adapter that maps JobStore calls to SQL updates on DuckQueue.

    This keeps the DAG engine decoupled while allowing persistence of
    SKIPPED/DONE/FAILED states into the `jobs` table.
    """

    def __init__(self, queue: Any):
        # We avoid importing DuckQueue at module import time to prevent
        # circular imports. At runtime we expect the object to behave like
        # DuckQueue (have _db_lock and conn attributes).
        self.queue = queue

    def get_job(self, job_id: str):
        return self.queue.get_job(job_id)

    def update_job_status(
        self,
        job_id: str,
        *,
        status: Optional[object] = None,
        skipped_at: Optional[datetime] = None,
        skip_reason: Optional[str] = None,
        skipped_by: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> None:
        sets: List[str] = []
        params: List[Any] = []

        status_val = None
        if status is not None:
            # Support either enum-like objects with `.value` or raw strings
            status_val = getattr(status, "value", None) or str(status)
            sets.append("status = ?")
            params.append(status_val)

        if skipped_at is not None:
            sets.append("skipped_at = ?")
            params.append(skipped_at)
        if skip_reason is not None:
            sets.append("skip_reason = ?")
            params.append(skip_reason)
        if skipped_by is not None:
            sets.append("skipped_by = ?")
            params.append(skipped_by)

        # If marking as skipped, finalize attempts to max_attempts in SQL.
        is_skipped_update = status_val == "skipped"

        if attempts is not None and not is_skipped_update:
            sets.append("attempts = ?")
            params.append(attempts)

        if not sets:
            return

        sql = f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?"
        params.append(job_id)

        with self.queue._db_lock:
            if is_skipped_update:
                # Append attempts = max_attempts to the SET clause
                sql = sql.replace(
                    "WHERE id = ?", ", attempts = max_attempts WHERE id = ?"
                )

            self.queue.conn.execute(sql, params)

    def bulk_update(self, updates: Iterable[Dict[str, Any]]) -> None:
        with self.queue._db_lock:
            for upd in updates:
                job_id = upd.pop("id", None)
                if not job_id:
                    continue
                self.update_job_status(job_id, **upd)
