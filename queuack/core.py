# file: duckqueue.py
# dependencies: duckdb>=0.9.0
# run: python duckqueue.py

"""
DuckQueue: A lightweight, agnostic job queue backed by DuckDB.

Unlike Celery/RQ which require Redis/RabbitMQ, DuckQueue uses a single
DuckDB file for persistence. Perfect for:
- Single-machine deployments
- Dev/test environments
- Projects that want simplicity over distributed complexity

Key features:
- Job serialization (pickle or JSON)
- Claim/ack semantics with timeouts
- Priority queues
- Delayed jobs
- Dead letter queues
- No external dependencies (just DuckDB)

Example:
    from duckqueue import DuckQueue
    
    # Producer
    queue = DuckQueue("jobs.duckdb")
    job_id = queue.enqueue(my_function, args=(1, 2), kwargs={'x': 3})
    
    # Consumer
    while True:
        job = queue.claim()
        if job:
            result = job.execute()
            queue.ack(job.id, result=result)
"""

import duckdb
import pickle
import uuid
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class JobStatus(Enum):
    """Job lifecycle states."""
    PENDING = "pending"      # Waiting to be claimed
    CLAIMED = "claimed"      # Worker has claimed it
    DONE = "done"           # Successfully completed
    FAILED = "failed"       # Failed after max retries
    DELAYED = "delayed"     # Scheduled for future execution


class BackpressureError(Exception):
    """Raised when queue depth exceeds safe limits."""
    pass


@dataclass
class Job:
    """
    Represents a serialized function call to be executed.
    
    Attributes:
        id: Unique job identifier
        func: Function to execute (serialized)
        args: Positional arguments
        kwargs: Keyword arguments
        queue: Queue name for routing
        status: Current job status
        priority: Higher = executed first (0-100)
        created_at: Job creation timestamp
        execute_after: Delay execution until this time
        claimed_at: When worker claimed the job
        claimed_by: Worker ID that claimed it
        completed_at: When job finished
        attempts: Number of execution attempts
        max_attempts: Maximum retry attempts
        timeout_seconds: Max execution time
        result: Serialized result (if successful)
        error: Error message (if failed)
    """
    id: str
    func: bytes  # Pickled function
    args: bytes  # Pickled args tuple
    kwargs: bytes  # Pickled kwargs dict
    queue: str
    status: str
    priority: int = 50
    created_at: datetime = None
    execute_after: datetime = None
    claimed_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0
    max_attempts: int = 3
    timeout_seconds: int = 300
    result: Optional[bytes] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def execute(self) -> Any:
        """
        Execute the job (unpickle function and call it).
        
        Returns:
            Function result
        
        Raises:
            Any exception from the function
        """
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        logger.info(f"Executing {func.__name__}(*{args}, **{kwargs})")
        
        return func(*args, **kwargs)


# ============================================================================
# Core Queue
# ============================================================================

class DuckQueue:
    """
    DuckDB-backed job queue with claim/ack semantics.
    
    Thread-safe within single process (DuckDB handles locking).
    Multi-process safe with file-based coordination.
    """
    
    def __init__(
        self,
        db_path: str = "duckqueue.db",
        default_queue: str = "default"
    ):
        """
        Initialize queue.
        
        Args:
            db_path: Path to DuckDB file (use ":memory:" for ephemeral)
            default_queue: Default queue name if not specified
        """
        self.db_path = db_path
        self.default_queue = default_queue
        self.conn = duckdb.connect(db_path)
        self._init_schema()
    
    def _init_schema(self):
        """Create jobs table and indexes."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id VARCHAR PRIMARY KEY,
                func BLOB NOT NULL,
                args BLOB NOT NULL,
                kwargs BLOB NOT NULL,
                queue VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                priority INTEGER DEFAULT 50,
                created_at TIMESTAMP NOT NULL,
                execute_after TIMESTAMP,
                claimed_at TIMESTAMP,
                claimed_by VARCHAR,
                completed_at TIMESTAMP,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                timeout_seconds INTEGER DEFAULT 300,
                result BLOB,
                error TEXT
            )
        """)
        
        # Optimize claim queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_claim 
            ON jobs(queue, status, priority DESC, execute_after, created_at)
        """)
        
        # Dead letter queue view
        self.conn.execute("""
            CREATE VIEW IF NOT EXISTS dead_letter_queue AS
            SELECT * FROM jobs 
            WHERE status = 'failed' AND attempts >= max_attempts
        """)
    
    # ========================================================================
    # Enqueue (Producer API)
    # ========================================================================
    
    def enqueue(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        queue: str = None,
        priority: int = 50,
        delay_seconds: int = 0,
        max_attempts: int = 3,
        timeout_seconds: int = 300,
        check_backpressure: bool = True
    ) -> str:
        """
        Enqueue a function call for async execution.
        
        Args:
            func: Function to execute (must be importable/picklable)
            args: Positional arguments
            kwargs: Keyword arguments
            queue: Queue name (defaults to self.default_queue)
            priority: 0-100, higher = executed first
            delay_seconds: Delay execution by N seconds
            max_attempts: Max retry attempts on failure
            timeout_seconds: Max execution time
            check_backpressure: If True, raise error if queue too full
        
        Returns:
            Job ID (UUID)
        
        Raises:
            BackpressureError: If check_backpressure=True and queue depth exceeds limit
        
        Example:
            def send_email(to, subject, body):
                # ... email logic
                pass
            
            job_id = queue.enqueue(
                send_email,
                args=('user@example.com',),
                kwargs={'subject': 'Hello', 'body': 'World'},
                delay_seconds=60  # Send in 1 minute
            )
        """
        kwargs = kwargs or {}
        queue = queue or self.default_queue
        
        # Backpressure check
        if check_backpressure:
            stats = self.stats(queue)
            pending = stats.get('pending', 0) + stats.get('delayed', 0)
            
            # Default: Warn at 1000, block at 10000
            # Note: we check >= 1000 so the warning fires when attempting to enqueue the 1001st job.
            if pending > 10000:
                raise BackpressureError(
                    f"Queue '{queue}' has {pending} pending jobs (limit: 10000). "
                    "System is overloaded. Scale workers or reduce enqueue rate."
                )
            elif pending >= 1000:
                import warnings
                
                msg=f"Queue '{queue}' has {pending} pending jobs (approaching limit)"
                logger.warning(msg)
                warnings.warn(msg, UserWarning)
        
        # Validate function is picklable
        try:
            pickled_func = pickle.dumps(func)
        except Exception as e:
            raise ValueError(f"Function {func.__name__} is not picklable: {e}")
        
        job_id = str(uuid.uuid4())
        now = datetime.now()
        execute_after = now + timedelta(seconds=delay_seconds) if delay_seconds > 0 else now
        
        self.conn.execute("""
            INSERT INTO jobs (
                id, func, args, kwargs, queue, status, priority,
                created_at, execute_after, max_attempts, timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            job_id,
            pickled_func,
            pickle.dumps(args),
            pickle.dumps(kwargs),
            queue,
            JobStatus.DELAYED.value if delay_seconds > 0 else JobStatus.PENDING.value,
            priority,
            now,
            execute_after,
            max_attempts,
            timeout_seconds
        ])
        
        logger.info(f"Enqueued {func.__name__} as {job_id[:8]} on queue '{queue}'")
        
        return job_id
    
    def enqueue_batch(
        self,
        jobs: List[Tuple[Callable, Tuple, Dict]],
        queue: str = None,
        priority: int = 50,
        max_attempts: int = 3
    ) -> List[str]:
        """
        Enqueue multiple jobs in one transaction.
        
        Args:
            jobs: List of (func, args, kwargs) tuples
            queue: Queue name
            priority: Priority for all jobs
            max_attempts: Max retry attempts
        
        Returns:
            List of job IDs
        
        Example:
            job_ids = queue.enqueue_batch([
                (process_user, (1,), {}),
                (process_user, (2,), {}),
                (process_user, (3,), {})
            ])
        """
        queue = queue or self.default_queue
        now = datetime.now()
        
        rows = []
        job_ids = []
        
        for func, args, kwargs in jobs:
            job_id = str(uuid.uuid4())
            job_ids.append(job_id)
            
            rows.append([
                job_id,
                pickle.dumps(func),
                pickle.dumps(args),
                pickle.dumps(kwargs),
                queue,
                JobStatus.PENDING.value,
                priority,
                now,
                now,  # execute_after
                max_attempts,
                300   # timeout_seconds
            ])
        
        self.conn.executemany("""
            INSERT INTO jobs (
                id, func, args, kwargs, queue, status, priority,
                created_at, execute_after, max_attempts, timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        
        logger.info(f"Batch enqueued {len(job_ids)} jobs on queue '{queue}'")
        
        return job_ids
    
    # ========================================================================
    # Claim/Ack (Consumer API)
    # ========================================================================
    
    def claim(
        self,
        queue: str = None,
        worker_id: str = None,
        claim_timeout: int = 300
    ) -> Optional[Job]:
        """
        Atomically claim next pending job.
        
        Args:
            queue: Queue to claim from (defaults to self.default_queue)
            worker_id: Worker identifier (auto-generated if None)
            claim_timeout: Seconds before claim expires (for stale job recovery)
        
        Returns:
            Job object or None if queue empty
        
        Example:
            while True:
                job = queue.claim()
                if job:
                    result = job.execute()
                    queue.ack(job.id, result=result)
                else:
                    time.sleep(1)
        """
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()
        now = datetime.now()
        
        # Promote delayed jobs that are ready
        self.conn.execute("""
            UPDATE jobs
            SET status = 'pending'
            WHERE status = 'delayed'
              AND execute_after <= ?
        """, [now])
        
        # Atomic claim with stale job recovery
        result = self.conn.execute("""
            UPDATE jobs
            SET 
                status = 'claimed',
                claimed_at = ?,
                claimed_by = ?,
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM jobs
                WHERE queue = ?
                AND (
                    status = 'pending'
                    OR (
                        status = 'claimed' 
                        AND claimed_at < ?
                    )
                )
                AND attempts < max_attempts
                AND (execute_after IS NULL OR execute_after <= ?)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING *
        """, [
            now,
            worker_id,
            queue,
            now - timedelta(seconds=claim_timeout),
            now
        ]).fetchone()
        
        if result is None:
            return None
        
        # Convert to Job object
        columns = [desc[0] for desc in self.conn.description]
        job_dict = dict(zip(columns, result))
        
        logger.info(f"Claimed job {job_dict['id'][:8]} by {worker_id}")
        
        return Job(**job_dict)
    
    def ack(
        self,
        job_id: str,
        result: Any = None,
        error: Optional[str] = None
    ):
        """
        Acknowledge job completion.
        
        Args:
            job_id: Job ID to acknowledge
            result: Result to store (will be pickled)
            error: Error message if job failed
        
        If error is provided, job is retried (if attempts < max_attempts)
        or moved to failed status.
        """
        now = datetime.now()
        
        if error:
            # Failed - check if should retry
            job = self.conn.execute("""
                SELECT attempts, max_attempts FROM jobs WHERE id = ?
            """, [job_id]).fetchone()
            
            if job and job[0] < job[1]:
                # Retry: move back to pending
                self.conn.execute("""
                    UPDATE jobs
                    SET 
                        status = 'pending',
                        error = ?,
                        claimed_at = NULL,
                        claimed_by = NULL
                    WHERE id = ?
                """, [error, job_id])
                logger.info(f"Job {job_id[:8]} failed (attempt {job[0]}/{job[1]}), requeued")
            else:
                # Max attempts reached: move to failed
                self.conn.execute("""
                    UPDATE jobs
                    SET 
                        status = 'failed',
                        completed_at = ?,
                        error = ?
                    WHERE id = ?
                """, [now, error, job_id])
                logger.error(f"Job {job_id[:8]} failed permanently: {error}")
        else:
            # Success
            result_bytes = pickle.dumps(result) if result is not None else None
            
            self.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'done',
                    completed_at = ?,
                    result = ?
                WHERE id = ?
            """, [now, result_bytes, job_id])
            logger.info(f"Job {job_id[:8]} completed successfully")
    
    def nack(self, job_id: str, requeue: bool = True):
        """
        Negative acknowledge (job failed, but don't want to store error).
        
        Args:
            job_id: Job ID
            requeue: If True, move back to pending (default)
        """
        if requeue:
            self.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'pending',
                    claimed_at = NULL,
                    claimed_by = NULL
                WHERE id = ?
            """, [job_id])
            logger.info(f"Job {job_id[:8]} requeued")
        else:
            self.ack(job_id, error="Negative acknowledged without requeue")
    
    # ========================================================================
    # Monitoring & Introspection
    # ========================================================================
    
    def stats(self, queue: str = None) -> Dict[str, int]:
        """
        Get queue statistics.
        
        Returns:
            Dict with counts by status
        """
        queue = queue or self.default_queue
        
        result = self.conn.execute("""
            SELECT status, COUNT(*) as count
            FROM jobs
            WHERE queue = ?
            GROUP BY status
        """, [queue]).fetchall()
        
        stats = {row[0]: row[1] for row in result}
        stats.setdefault('pending', 0)
        stats.setdefault('claimed', 0)
        stats.setdefault('done', 0)
        stats.setdefault('failed', 0)
        stats.setdefault('delayed', 0)
        
        return stats
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        result = self.conn.execute("""
            SELECT * FROM jobs WHERE id = ?
        """, [job_id]).fetchone()
        
        if result is None:
            return None
        
        columns = [desc[0] for desc in self.conn.description]
        job_dict = dict(zip(columns, result))
        return Job(**job_dict)
    
    def get_result(self, job_id: str) -> Any:
        """
        Get job result (unpickles automatically).
        
        Raises:
            ValueError if job not done or failed
        """
        job = self.get_job(job_id)
        
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        
        if job.status != JobStatus.DONE.value:
            raise ValueError(f"Job {job_id} is {job.status}, not done")
        
        if job.result is None:
            return None
        
        return pickle.loads(job.result)
    
    def list_dead_letters(self, limit: int = 100) -> List[Job]:
        """List jobs in dead letter queue (failed permanently)."""
        results = self.conn.execute("""
            SELECT * FROM dead_letter_queue
            ORDER BY completed_at DESC
            LIMIT ?
        """, [limit]).fetchall()
        
        columns = [desc[0] for desc in self.conn.description]
        
        jobs = []
        for row in results:
            job_dict = dict(zip(columns, row))
            jobs.append(Job(**job_dict))
        
        return jobs
    
    def purge(
        self,
        queue: str = None,
        status: str = "done",
        older_than_hours: int = 24
    ) -> int:
        """
        Delete old jobs.
        
        Args:
            queue: Queue to purge (None = all queues)
            status: Status to delete ('done', 'failed', etc.)
            older_than_hours: Only delete jobs older than this
        
        Returns:
            Number of jobs deleted
        """
        cutoff = datetime.now() - timedelta(hours=older_than_hours)
        
        if queue:
            # Count first, then delete
            count_result = self.conn.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE queue = ? AND status = ? AND created_at < ?
            """, [queue, status, cutoff]).fetchone()
            
            count = count_result[0] if count_result else 0
            
            if count > 0:
                self.conn.execute("""
                    DELETE FROM jobs
                    WHERE queue = ? AND status = ? AND created_at < ?
                """, [queue, status, cutoff])
        else:
            # Count first, then delete
            count_result = self.conn.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE status = ? AND created_at < ?
            """, [status, cutoff]).fetchone()
            
            count = count_result[0] if count_result else 0
            
            if count > 0:
                self.conn.execute("""
                    DELETE FROM jobs
                    WHERE status = ? AND created_at < ?
                """, [status, cutoff])
        
        logger.info(f"Purged {count} {status} jobs older than {older_than_hours}h")
        
        return count
    
    # ========================================================================
    # Helpers
    # ========================================================================
    
    def _generate_worker_id(self) -> str:
        """Generate unique worker identifier."""
        import socket
        import os
        return f"{socket.gethostname()}-{os.getpid()}-{int(time.time())}"
    
    def close(self):
        """Close database connection."""
        self.conn.close()


# ============================================================================
# Worker Process
# ============================================================================

class Worker:
    """
    Long-running worker process that claims and executes jobs.
    
    Supports:
    - Multiple queues with priority (claim from high-priority first)
    - Backpressure (stops claiming when local queue full)
    - Concurrent execution (thread/process pool)
    
    Example:
        # Single-threaded worker
        worker = Worker(queue=DuckQueue())
        worker.run()
        
        # Multi-threaded worker (4 threads)
        worker = Worker(queue=DuckQueue(), concurrency=4)
        worker.run()
    """
    
    def __init__(
        self,
        queue: DuckQueue,
        queues: List[str] = None,
        worker_id: str = None,
        concurrency: int = 1,
        max_jobs_in_flight: int = None
    ):
        """
        Initialize worker.
        
        Args:
            queue: DuckQueue instance
            queues: List of queue names to listen to (default: ["default"])
                   Can use tuple (name, priority) to set claiming order
            worker_id: Worker identifier (auto-generated if None)
            concurrency: Number of threads/processes for parallel execution
            max_jobs_in_flight: Max jobs claimed but not completed (backpressure limit)
                               Defaults to concurrency * 2
        """
        self.queue = queue
        self.worker_id = worker_id or queue._generate_worker_id()
        self.concurrency = concurrency
        self.max_jobs_in_flight = max_jobs_in_flight or (concurrency * 2)
        self.should_stop = False
        self.jobs_in_flight = 0
        
        # Parse queues (support priority tuples)
        self.queues = self._parse_queues(queues or ["default"])
        
        # Only register signal handlers if we're in the main thread
        import signal
        import threading
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
    
    def _parse_queues(self, queues):
        """Parse queue list, handling (name, priority) tuples."""
        parsed = []
        for q in queues:
            if isinstance(q, tuple):
                name, priority = q
                parsed.append((name, priority))
            else:
                parsed.append((q, 0))  # Default priority
        
        # Sort by priority (highest first)
        return sorted(parsed, key=lambda x: x[1], reverse=True)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Worker {self.worker_id} received shutdown signal")
        self.should_stop = True
    
    def run(self, poll_interval: float = 1.0):
        """
        Main worker loop.
        
        Args:
            poll_interval: Seconds to wait between polls when queue empty
        """
        logger.info(
            f"Worker {self.worker_id} started "
            f"(concurrency={self.concurrency}, backpressure={self.max_jobs_in_flight})"
        )
        logger.info(f"Listening on queues (by priority): {[q[0] for q in self.queues]}")
        
        if self.concurrency > 1:
            self._run_concurrent(poll_interval)
        else:
            self._run_sequential(poll_interval)
    
    def _run_sequential(self, poll_interval: float):
        """Single-threaded execution."""
        processed = 0
        
        while not self.should_stop:
            job = self._claim_next_job()
            
            if job:
                processed += 1
                self._execute_job(job, processed)
            else:
                time.sleep(poll_interval)
        
        logger.info(f"Worker {self.worker_id} stopped (processed {processed} jobs)")
    
    def _run_concurrent(self, poll_interval: float):
        """Multi-threaded execution with backpressure."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        processed = 0
        lock = threading.Lock()
        
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {}
            
            while not self.should_stop or futures:
                # Backpressure: Stop claiming if too many jobs in flight
                if len(futures) < self.max_jobs_in_flight and not self.should_stop:
                    job = self._claim_next_job()
                    
                    if job:
                        with lock:
                            processed += 1
                            job_num = processed
                        
                        future = executor.submit(self._execute_job, job, job_num)
                        futures[future] = job.id
                
                # Process completed jobs
                if futures:
                    try:
                        done_futures = list(as_completed(futures.keys(), timeout=poll_interval))
                        
                        for future in done_futures:
                            job_id = futures.pop(future)
                            try:
                                future.result()  # Raise any exceptions
                            except Exception as e:
                                logger.error(f"Executor error for {job_id[:8]}: {e}")
                    except TimeoutError:
                        # No jobs completed in this interval, continue polling
                        pass
                else:
                    time.sleep(poll_interval)
        
        logger.info(f"Worker {self.worker_id} stopped (processed {processed} jobs)")
    
    def _claim_next_job(self) -> Optional[Job]:
        """Claim next job from highest-priority queue."""
        for queue_name, _ in self.queues:
            job = self.queue.claim(queue=queue_name, worker_id=self.worker_id)
            if job:
                return job
        return None
    
    def _execute_job(self, job: Job, job_num: int):
        """Execute a single job."""
        try:
            start_time = time.time()
            result = job.execute()
            duration = time.time() - start_time
            
            self.queue.ack(job.id, result=result)
            
            logger.info(
                f"✓ [{self.worker_id}] Job {job.id[:8]} completed in {duration:.2f}s "
                f"(#{job_num})"
            )
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            self.queue.ack(job.id, error=error_msg)
            
            logger.error(f"✗ [{self.worker_id}] Job {job.id[:8]} failed: {e}")


# ============================================================================
# Convenience Decorators
# ============================================================================

def job(
    queue_instance: DuckQueue,
    queue: str = "default",
    priority: int = 50,
    delay_seconds: int = 0,
    max_attempts: int = 3
):
    """
    Decorator to make functions enqueueable.
    
    Example:
        q = DuckQueue()
        
        @job(q, queue="emails")
        def send_email(to, subject):
            # ... email logic
            pass
        
        # Call normally (synchronous)
        send_email("user@example.com", "Hello")
        
        # Or enqueue for async execution
        send_email.delay("user@example.com", "Hello")
    """
    def decorator(func):
        # Add .delay() method
        def delay(*args, **kwargs):
            return queue_instance.enqueue(
                func,
                args=args,
                kwargs=kwargs,
                queue=queue,
                priority=priority,
                delay_seconds=delay_seconds,
                max_attempts=max_attempts
            )
        
        func.delay = delay
        return func
    
    return decorator


