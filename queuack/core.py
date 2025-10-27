# file: core.py

"""
Queuack: A lightweight, agnostic job queue backed by DuckDB.

Unlike Celery/RQ which require Redis/RabbitMQ, Queuack uses a single
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
    from queuack import DuckQueue

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

import logging
import os
import pickle
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import duckdb

from .constants import DEFAULT_POLL_TIMEOUT, WORKER_DRAIN_SECONDS


@dataclass
class QueueConfig:
    """Per-queue tunables centralizing runtime configuration."""

    values_threshold: int = None
    dep_chunk_size: int = None
    poll_timeout: float = DEFAULT_POLL_TIMEOUT


from .dag import DAG, DAGContext
from .data_models import BackpressureError, Job
from .status import JobStatus

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
        default_queue: str = "default",
        workers_num: Optional[int] = 1,
        worker_concurrency: int = 1,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
        # Dependency insertion tuning (optional per-queue overrides)
        values_threshold: Optional[int] = None,
        dep_chunk_size: Optional[int] = None,
        logger: Optional[logging.Logger] = None,
        serialization: str = "pickle",  # "pickle" or "json_ref"
        # BULLETPROOF CONCURRENCY CONTROL
        force_memory_db: bool = False,  # Override auto-migration for :memory:
    ):
        """Initialize queue with schema creation."""
        if workers_num is not None and workers_num <= 0:
            raise ValueError("workers_num must be positive or None")
        if worker_concurrency <= 0:
            raise ValueError("worker_concurrency must be positive")

        # Initialize logger FIRST (needed for auto-migration)
        self.logger = logger or logging.getLogger(__name__)

        # BULLETPROOF FIX: Auto-migrate unsafe :memory: + multiple workers
        original_db_path = db_path
        self._temp_file_cleanup = None  # Initialize before resolution
        self.db_path = self._resolve_safe_db_path(db_path, workers_num, force_memory_db)
        self._was_auto_migrated = self.db_path != original_db_path

        self.default_queue = default_queue
        self._workers_num = workers_num
        self._worker_concurrency = worker_concurrency
        self.serialization = serialization

        # Centralized per-queue configuration object. Values fall back to
        # repository defaults when not provided.
        from .constants import DEP_CHUNK_SIZE, VALUES_THRESHOLD

        self.config = QueueConfig(
            values_threshold=(
                values_threshold if values_threshold is not None else VALUES_THRESHOLD
            ),
            dep_chunk_size=(
                dep_chunk_size if dep_chunk_size is not None else DEP_CHUNK_SIZE
            ),
            poll_timeout=poll_timeout,
        )

        # Backwards-compatible attributes for existing code
        self.values_threshold = self.config.values_threshold
        self.dep_chunk_size = self.config.dep_chunk_size
        self._poll_timeout = self.config.poll_timeout
        self._closed = False

        # Create connection pool
        self._conn_pool = ConnectionPool(self.db_path)

        self._worker_pool = None

        # Initialize database schema
        self._init_schema()

    def _resolve_safe_db_path(
        self, db_path: str, workers_num: Optional[int], force_memory_db: bool
    ) -> str:
        """
        BULLETPROOF CONCURRENCY FIX: Auto-migrate unsafe configurations.

        :memory: + multiple workers = SEGFAULTS due to non-thread-safe DuckDB connections.
        This method automatically converts such configurations to temp files for safety.

        Returns:
            str: Safe database path (original path or auto-created temp file)
        """
        # Safe configurations - no migration needed
        if db_path != ":memory:":
            return db_path  # File-based DB is always safe

        if workers_num is None or workers_num <= 1:
            return db_path  # Single worker is safe with :memory:

        if force_memory_db:
            # User explicitly wants :memory: despite dangers
            self.logger.warning(
                "DANGER: force_memory_db=True with :memory: + multiple workers. "
                "This configuration is known to cause segmentation faults."
            )
            return db_path

        # UNSAFE CONFIGURATION: :memory: + multiple workers
        # Auto-migrate to temp file for safety
        import atexit
        import os
        import tempfile

        # Get a temp path but don't create the file (DuckDB will create it)
        temp_dir = tempfile.gettempdir()
        temp_name = f"auto_migrated_{os.getpid()}_{id(self)}.duckqueue.db"
        temp_path = os.path.join(temp_dir, temp_name)

        # Store cleanup info
        self._temp_file_cleanup = temp_path

        # Register cleanup on exit
        def cleanup_temp_file():
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except Exception:
                pass  # Ignore cleanup errors

        atexit.register(cleanup_temp_file)

        self.logger.info(
            f"AUTO-MIGRATED: :memory: + {workers_num} workers → {temp_path} "
            f"(prevents segfaults, use force_memory_db=True to override)"
        )

        return temp_path

    def _cleanup_auto_migrated_db(self):
        """Clean up auto-created temporary database file."""
        if self._temp_file_cleanup:
            try:
                import os

                if os.path.exists(self._temp_file_cleanup):
                    os.unlink(self._temp_file_cleanup)
                    self.logger.debug(
                        f"Cleaned up auto-migrated database: {self._temp_file_cleanup}"
                    )
            except Exception as e:
                self.logger.debug(
                    f"Could not clean up temp database {self._temp_file_cleanup}: {e}"
                )

    # Backpressure thresholds are configurable via classmethods so tests
    # or subclasses can override them for faster runs.
    @classmethod
    def backpressure_warning_threshold(cls) -> int:
        """Return the number of pending jobs at which we issue a warning.

        Default: 1000
        """
        return 1000

    @classmethod
    def backpressure_block_threshold(cls) -> int:
        """Return the number of pending jobs at which we block/enforce backpressure.

        Default: 10000
        """
        return 10000

    @property
    def conn(self):
        """Get thread-local connection."""
        # For memory databases, we need to be more careful about concurrent access
        if self.db_path == ":memory:":
            # Return the connection but warn about potential thread safety issues
            return self._conn_pool.get_connection()
        else:
            return self._conn_pool.get_connection()

    def connection_context(self):
        """Get a connection context manager that handles locking for shared connections."""
        return self._conn_pool.connection_context()

    def _execute_with_connection_lock(self, func, *args, **kwargs):
        """Execute a function that requires database access with proper locking."""
        if self.db_path == ":memory:":
            # For memory databases, use lock to serialize access
            with self._conn_pool._connection_lock:
                return func(*args, **kwargs)
        else:
            # For file databases, no lock needed (thread-local connections)
            return func(*args, **kwargs)

    def __enter__(self):
        """Context manager entry - start workers if configured."""

        # Start background workers when entering context only if an explicit
        # number of workers was configured. If `workers_num` is None the
        # context manager should not start any workers (tests rely on this
        # semantics). When callers want automatic workers they can rely on
        # the default constructor behavior (passing workers_num=1).
        if self._workers_num is not None:
            self.start_workers(
                num_workers=self._workers_num,
                concurrency=self._worker_concurrency,
                daemon=True,
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

        # Clean up auto-created temp files
        self._cleanup_auto_migrated_db()

    def start_workers(
        self, num_workers: int = 4, concurrency: int = 1, daemon: bool = True
    ):
        """Start background workers that process jobs automatically."""
        # BULLETPROOF: This should now be safe due to auto-migration in __init__
        if self.db_path == ":memory:" and num_workers > 1:
            self.logger.warning(
                "DANGEROUS: Using :memory: database with multiple workers. "
                "This configuration causes segfaults. Use force_memory_db=False "
                "to enable auto-migration to temp files."
            )

        self._worker_pool = WorkerPool(self, num_workers, concurrency)
        self._worker_pool.start()

        if not daemon:
            # Block and wait for workers
            try:
                while True:
                    time.sleep(self._poll_timeout)
            except KeyboardInterrupt:
                self._worker_pool.stop()

    def stop_workers(self):
        """Stop background workers."""
        if self._worker_pool is not None:
            self._worker_pool.stop()
            self._worker_pool = None

    def _init_schema(self):
        """Initialize database schema.

        For :memory: databases, create ONE connection before marking ready,
        and share it via the connection pool. This ensuresall threads see
        the same schema and data.
        """
        # Block all connections until schema is ready
        self._conn_pool.mark_initializing()

        # Log the database path being used (for debugging auto-migration)
        if self._was_auto_migrated:
            self.logger.info(
                f"Auto-migrated to safe database: {self.db_path} "
                f"(from :memory: for multi-worker safety)"
            )

        try:
            init_conn = duckdb.connect(self.db_path)

            # For :memory:, create the shared connection here
            if self._conn_pool._use_shared_memory:
                # Create schema on this connection
                self._create_schema(init_conn)

                # Store as the global shared connection BEFORE marking ready
                # This ensures get_connection() will return this exact connection
                self._conn_pool.set_global_connection(init_conn)

            # For file DBs, create a temporary connection just for schema init
            else:
                try:
                    self._create_schema(init_conn)
                finally:
                    # Close the init connection - threads will create their own
                    init_conn.close()

        except Exception:
            # If initialization fails, still mark as ready to avoid deadlock
            # but re-raise so the constructor fails
            self._conn_pool.mark_ready()
            raise

        finally:
            # Now it's safe for threads to get connections
            self._conn_pool.mark_ready()

    def _create_schema(self, conn):
        """Create database schema on the given connection."""
        # Use CREATE IF NOT EXISTS for idempotency
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id VARCHAR PRIMARY KEY,
                dag_run_id VARCHAR,
                node_name VARCHAR,
                dependency_mode VARCHAR DEFAULT 'all',
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
                timeout_seconds REAL DEFAULT 300,
                result BLOB,
                error TEXT,
                skipped_at TIMESTAMP,
                skip_reason TEXT,
                skipped_by VARCHAR
            )
        """)

        # Indexes for efficient querying
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_claim 
            ON jobs(queue, status, priority DESC, created_at, attempts, max_attempts, execute_after)
        """)

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_dag_run 
            ON jobs(dag_run_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_node_name 
            ON jobs(node_name)
            """
        )

        # Dead letter queue view
        conn.execute("""
            CREATE VIEW IF NOT EXISTS dead_letter_queue AS
            SELECT * FROM jobs 
            WHERE status = 'failed' AND attempts >= max_attempts
        """)

        # Dependency table for DAG support
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_dependencies (
                child_job_id VARCHAR NOT NULL,
                parent_job_id VARCHAR NOT NULL,
                PRIMARY KEY (child_job_id, parent_job_id)
            )
        """)

        # Better dependency indexes
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_dependencies_parent 
            ON job_dependencies(parent_job_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_dependencies_child 
            ON job_dependencies(child_job_id)
        """)

        # Composite index for dependency checks with status
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_dependencies_child_parent
            ON job_dependencies(child_job_id, parent_job_id)
        """)

        # DAG runs table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dag_runs (
                id VARCHAR PRIMARY KEY,
                parent_job_id VARCHAR,
                name VARCHAR NOT NULL,
                description TEXT,
                created_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                status VARCHAR NOT NULL,
                metadata TEXT
            )
            """
        )

        # Indexes for DAG queries

        # Index for querying by name
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dag_runs_name 
            ON dag_runs(name)
            """
        )

        # Add index for querying sub-DAGs
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dag_runs_parent 
            ON dag_runs(parent_job_id)
            """
        )

        # Other indexes
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dag_runs_status 
            ON dag_runs(status)
            """
        )

        # Statistics view
        conn.execute(
            """
            CREATE OR REPLACE VIEW dag_run_stats AS
            SELECT 
                dr.id as dag_run_id,
                dr.name as dag_name,
                dr.status as dag_status,
                dr.created_at,
                dr.completed_at,
                COUNT(j.id) as total_jobs,
                SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END) as completed_jobs,
                SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) as failed_jobs,
                SUM(CASE WHEN j.status = 'pending' THEN 1 ELSE 0 END) as pending_jobs,
                SUM(CASE WHEN j.status = 'claimed' THEN 1 ELSE 0 END) as running_jobs,
                SUM(CASE WHEN j.status = 'skipped' THEN 1 ELSE 0 END) as skipped_jobs
            FROM dag_runs dr
            LEFT JOIN jobs j ON dr.id = j.dag_run_id
            GROUP BY dr.id, dr.name, dr.status, dr.created_at, dr.completed_at
        """
        )

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
        timeout_seconds: float = 300,
        check_backpressure: bool = True,
        depends_on: Union[str, List[str]] = None,
        dependency_mode: str = "all",
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
            dependency_mode: 'all' or 'any' - how to handle multiple parent dependencies

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
            pending = stats.get("pending", 0) + stats.get("delayed", 0)

            # Configurable thresholds (defaults: warn=1000, block=10000)
            warn_threshold = self.backpressure_warning_threshold()
            block_threshold = self.backpressure_block_threshold()

            # Note: we check >= warn_threshold so the warning fires when attempting to enqueue the
            # (warn_threshold+1)th job.
            if pending > block_threshold:
                raise BackpressureError(
                    f"Queue '{queue}' has {pending} pending jobs (limit: {block_threshold}). "
                    "System is overloaded. Scale workers or reduce enqueue rate."
                )
            # Warn when the new job would push us past the warning threshold.
            elif (pending + 1) > warn_threshold:
                import warnings

                msg = f"Queue '{queue}' has {pending} pending jobs (approaching limit)"
                self.logger.warning(msg)
                warnings.warn(msg, UserWarning)

        # Validate function is picklable
        try:
            pickled_func = pickle.dumps(func)
        except Exception as e:
            error_msg = f"\nFunction {getattr(func, '__name__', repr(func))} is not picklable: {e}\n\nQueuack requires functions to be picklable for serialization. Common issues:\n\n1. Lambdas: Use named functions instead\n   ❌ queue.enqueue(lambda x: x*2, args=(5,))\n   ✅ def double(x): return x*2\n      queue.enqueue(double, args=(5,))\n\n2. Nested/local functions: Move to module level\n   ❌ def outer():\n       def inner(): pass\n       queue.enqueue(inner)\n   ✅ def inner(): pass\n      def outer():\n          queue.enqueue(inner)\n\n3. Closures with unpicklable objects: Ensure all captured variables are picklable\n\nFor more complex cases, consider using JSON-serializable function references.\n"
            raise ValueError(error_msg)

        job_id = str(uuid.uuid4())
        now = datetime.now()
        execute_after = (
            now + timedelta(seconds=delay_seconds) if delay_seconds > 0 else now
        )

        with self.connection_context() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, func, args, kwargs, queue, status, priority,
                    created_at, execute_after, max_attempts, timeout_seconds, dependency_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                [
                    job_id,
                    pickled_func,
                    pickle.dumps(args),
                    pickle.dumps(kwargs),
                    queue,
                    JobStatus.DELAYED.value
                    if delay_seconds > 0
                    else JobStatus.PENDING.value,
                    priority,
                    now,
                    execute_after,
                    max_attempts,
                    timeout_seconds,
                    dependency_mode,
                ],
            )

            # Persist dependencies if provided
            if depends_on:
                parent_ids = (
                    [depends_on] if isinstance(depends_on, str) else list(depends_on)
                )
                for pid in parent_ids:
                    try:
                        conn.execute(
                            "INSERT INTO job_dependencies (child_job_id, parent_job_id) VALUES (?, ?)",
                            [job_id, pid],
                        )
                    except Exception:
                        # ignore duplicate/missing parent handling here; validation may be added later
                        pass

            conn.commit()

        self.logger.info(f"Enqueued {func.__name__} as {job_id[:8]} on queue '{queue}'")

        return job_id

    def enqueue_batch(
        self,
        jobs: List[Tuple[Callable, Tuple, Dict]],
        queue: str = None,
        priority: int = 50,
        max_attempts: int = 3,
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

        # Handle empty batch case first
        if not jobs:
            return []

        rows = []
        job_ids = []

        for func, args, kwargs in jobs:
            job_id = str(uuid.uuid4())
            job_ids.append(job_id)

            rows.append(
                [
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
                    300,  # timeout_seconds
                ]
            )

        self.conn.executemany(
            """
            INSERT INTO jobs (
                id, func, args, kwargs, queue, status, priority,
                created_at, execute_after, max_attempts, timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            rows,
        )
        self.conn.commit()

        self.logger.info(f"Batch enqueued {len(job_ids)} jobs on queue '{queue}'")

        return job_ids

    # ========================================================================
    # Claim/Ack (Consumer API)
    # ========================================================================

    def ack(
        self,
        job_id: str,
        result: Any = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        """Acknowledge job completion."""
        return self._execute_with_connection_lock(
            self._ack_internal, job_id, result, error, worker_id
        )

    def _ack_internal(self, job_id, result, error, worker_id):
        """Internal ack method that runs with proper locking."""
        try:
            self._attempt_ack(job_id, result, error, worker_id)
        except Exception as e:
            # Log transaction conflicts but don't fail acks
            if "TransactionContext Error" in str(e) or "write-write conflict" in str(e):
                self.logger.warning(
                    f"Transaction conflict acking job {job_id[:8]}: {e}"
                )
                return
            else:
                raise

    def _ack_with_retry(
        self,
        job_id: str,
        result: Any = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
        max_retries: int = 2,
    ):
        """Internal ack method with transaction conflict retry logic."""
        for attempt in range(max_retries):
            try:
                self._attempt_ack(job_id, result, error, worker_id)
                return
            except Exception as e:
                # Only retry on specific transaction conflicts
                if "write-write conflict" in str(e) or (
                    "TransactionContext Error" in str(e) and "commit" in str(e)
                ):
                    if attempt < max_retries - 1:
                        # Very short sleep
                        time.sleep(0.002 + attempt * 0.002)
                        continue
                    else:
                        # Log warning but don't raise to avoid worker crashes
                        self.logger.warning(
                            f"Failed to ack job {job_id[:8]} after {max_retries} attempts: {e}"
                        )
                        return
                else:
                    # Re-raise non-transaction errors immediately
                    raise

    def _attempt_ack(
        self,
        job_id: str,
        result: Any = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        """Single attempt to acknowledge job completion."""
        now = datetime.now()

        try:
            if error:
                job = self.conn.execute(
                    "SELECT attempts, max_attempts FROM jobs WHERE id = ?", [job_id]
                ).fetchone()
                self.conn.commit()

                if job and job[0] < job[1]:
                    # Retry
                    self.conn.execute(
                        "UPDATE jobs SET status = 'pending', error = ?, claimed_at = NULL, claimed_by = NULL WHERE id = ?",
                        [error, job_id],
                    )
                    self.conn.commit()

                    self.logger.info(
                        f"Job {job_id[:8]} failed (attempt {job[0]}/{job[1]}), requeued"
                    )
                else:
                    # Failed permanently
                    self.conn.execute(
                        "UPDATE jobs SET status = 'failed', completed_at = ?, error = ? WHERE id = ?",
                        [now, error, job_id],
                    )
                    self.conn.commit()
                    self.logger.error(f"Job {job_id[:8]} failed permanently: {error}")

                    # Propagate in separate transaction to avoid long-running locks
                    try:
                        while True:
                            updated = self.conn.execute(
                                """
                                WITH RECURSIVE descendants(child_id) AS (...)
                                UPDATE jobs SET status = 'skipped', ...
                                RETURNING jobs.id
                                """,
                                [
                                    job_id,
                                    now,
                                    f"parent_failed:{job_id}",
                                    "queuack",
                                    now,
                                ],
                            ).fetchall()
                            self.conn.commit()

                            if not updated:
                                break
                    except Exception as e:
                        self.logger.exception(f"Error propagating skipped state: {e}")
                        try:
                            self.conn.rollback()
                        except Exception:
                            pass
                    return  # Already committed
            else:
                # Success
                result_bytes = pickle.dumps(result) if result is not None else None
                self.conn.execute(
                    "UPDATE jobs SET status = 'done', completed_at = ?, result = ? WHERE id = ?",
                    [now, result_bytes, job_id],
                )
                self.logger.info(f"Job {job_id[:8]} completed successfully")

            # Commit the transaction
            self.conn.commit()

        except Exception:
            # Rollback on error
            try:
                self.conn.rollback()
            except Exception:
                pass
            raise

    def claim(
        self, queue: str = None, worker_id: str = None, claim_timeout: int = 300
    ) -> Optional[Job]:
        """
        Atomically claim next pending job.
        """
        return self._execute_with_connection_lock(
            self._claim_internal, queue, worker_id, claim_timeout
        )

    def _claim_internal(self, queue, worker_id, claim_timeout):
        """Internal claim method that runs with proper locking."""
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()

        try:
            return self._attempt_claim(queue, worker_id, claim_timeout)
        except Exception as e:
            # Log transaction conflicts but don't crash workers
            if "TransactionContext Error" in str(e) or "Conflict" in str(e):
                self.logger.debug(f"Transaction conflict claiming job: {e}")
                return None
            else:
                raise

    def _claim_with_retry(
        self,
        queue: str = None,
        worker_id: str = None,
        claim_timeout: int = 300,
        max_retries: int = 2,
    ) -> Optional[Job]:
        """Internal claim method with transaction conflict retry logic."""
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()

        for attempt in range(max_retries):
            try:
                return self._attempt_claim(queue, worker_id, claim_timeout)
            except Exception as e:
                # Only retry on specific DuckDB transaction conflicts
                if (
                    "TransactionContext Error" in str(e) and "Conflict" in str(e)
                ) or "tuple deletion" in str(e):
                    if attempt < max_retries - 1:
                        # Very short sleep to avoid contention
                        time.sleep(0.001 + attempt * 0.001)
                        continue
                    else:
                        # Log and return None instead of raising to avoid worker crashes
                        self.logger.debug(
                            f"Failed to claim job after {max_retries} attempts: {e}"
                        )
                        return None
                else:
                    # Re-raise non-transaction errors immediately
                    raise

        return None

    def _attempt_claim(
        self, queue: str, worker_id: str, claim_timeout: int
    ) -> Optional[Job]:
        """Single attempt to claim a job."""
        now = datetime.now()
        conn = self.conn

        # Promote delayed jobs that are ready
        conn.execute(
            """
            UPDATE jobs
            SET status = 'pending'
            WHERE status = 'delayed'
            AND execute_after <= ?
        """,
            [now],
        )
        conn.commit()

        # Atomic claim with stale job recovery
        cursor = conn.execute(
            """
            UPDATE jobs
            SET
                status = 'claimed',
                claimed_at = ?,
                claimed_by = ?,
                attempts = attempts + 1
            WHERE id = (
                    SELECT j.id FROM jobs AS j
                    WHERE j.queue = ?
                    AND (
                        j.status = 'pending'
                        OR (
                            j.status = 'claimed'
                            AND j.claimed_at < ?
                        )
                    )
                    AND j.attempts < j.max_attempts
                    AND (j.execute_after IS NULL OR j.execute_after <= ?)
                    AND (
                        NOT EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            WHERE jd.child_job_id = j.id
                        )
                        OR
                        (j.dependency_mode = 'all' AND NOT EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            JOIN jobs pj ON jd.parent_job_id = pj.id
                            WHERE jd.child_job_id = j.id
                            AND pj.status != 'done'
                        ))
                        OR
                        (j.dependency_mode = 'any' AND EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            JOIN jobs pj ON jd.parent_job_id = pj.id
                            WHERE jd.child_job_id = j.id
                            AND pj.status = 'done'
                        ))
                    )
                    ORDER BY j.priority DESC, j.created_at ASC
                    LIMIT 1
                )
                RETURNING *
            """,
            [now, worker_id, queue, now - timedelta(seconds=claim_timeout), now],
        )

        # CRITICAL FIX: Fetch BEFORE commit
        result = cursor.fetchone()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        # Commit AFTER fetching
        conn.commit()

        if result is None:
            return None

        # Convert to Job object
        job_dict = dict(zip(columns, result))

        self.logger.info(f"Claimed job {job_dict['id'][:8]} by {worker_id}")

        # Expose the DuckQueue instance on the claiming thread
        import threading

        try:
            threading.current_thread()._queuack_queue = self
        except Exception:
            pass

        return Job(**job_dict)

    def claim_batch(
        self,
        count: int = 10,
        queue: str = None,
        worker_id: str = None,
        claim_timeout: int = 300,
    ) -> List[Job]:
        """
        Atomically claim multiple jobs at once.
        """
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()

        try:
            return self._attempt_claim_batch(count, queue, worker_id, claim_timeout)
        except Exception as e:
            # Log transaction conflicts but return empty list
            if "TransactionContext Error" in str(e) or "Conflict" in str(e):
                self.logger.debug(f"Transaction conflict in batch claim: {e}")
                return []
            else:
                raise

    def _claim_batch_with_retry(
        self,
        count: int,
        queue: str = None,
        worker_id: str = None,
        claim_timeout: int = 300,
        max_retries: int = 1,  # Even more conservative for batch operations
    ) -> List[Job]:
        """Internal claim_batch method with transaction conflict retry logic."""
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()

        for attempt in range(max_retries):
            try:
                return self._attempt_claim_batch(count, queue, worker_id, claim_timeout)
            except Exception as e:
                # Only retry on specific conflicts, be very conservative
                if "TransactionContext Error" in str(e) and "Conflict" in str(e):
                    if attempt < max_retries - 1:
                        # Minimal sleep
                        time.sleep(0.001)
                        continue
                    else:
                        # Return empty list instead of raising
                        self.logger.debug(
                            f"Failed to claim batch after {max_retries} attempts: {e}"
                        )
                        return []
                else:
                    # Re-raise non-transaction errors immediately
                    raise

        return []

    def _attempt_claim_batch(
        self, count: int, queue: str, worker_id: str, claim_timeout: int
    ) -> List[Job]:
        """Single attempt to claim multiple jobs."""
        now = datetime.now()

        with self.connection_context() as conn:
            # Promote delayed jobs
            conn.execute(
                """
                UPDATE jobs
                SET status = 'pending'
                WHERE status = 'delayed'
                AND execute_after <= ?
            """,
                [now],
            )

            # Claim multiple jobs in ONE transaction
            cursor = conn.execute(
                """
                WITH claimable AS (
                    SELECT j.id
                    FROM jobs AS j
                    WHERE j.queue = ?
                    AND (
                        j.status = 'pending'
                        OR (j.status = 'claimed' AND j.claimed_at < ?)
                    )
                    AND j.attempts < j.max_attempts
                    AND (j.execute_after IS NULL OR j.execute_after <= ?)
                    AND (
                        NOT EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            WHERE jd.child_job_id = j.id
                        )
                        OR
                        (j.dependency_mode = 'all' AND NOT EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            JOIN jobs pj ON jd.parent_job_id = pj.id
                            WHERE jd.child_job_id = j.id
                            AND pj.status != 'done'
                        ))
                        OR
                        (j.dependency_mode = 'any' AND EXISTS (
                            SELECT 1 FROM job_dependencies jd
                            JOIN jobs pj ON jd.parent_job_id = pj.id
                            WHERE jd.child_job_id = j.id
                            AND pj.status = 'done'
                        ))
                    )
                    ORDER BY j.priority DESC, j.created_at ASC
                    LIMIT ?
                )
                UPDATE jobs
                SET
                    status = 'claimed',
                    claimed_at = ?,
                    claimed_by = ?,
                    attempts = attempts + 1
                WHERE id IN (SELECT id FROM claimable)
                RETURNING *
            """,
                [
                    queue,
                    now - timedelta(seconds=claim_timeout),
                    now,
                    count,
                    now,
                    worker_id,
                ],
            )

            # CRITICAL FIX: Fetch BEFORE commit
            results = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Commit AFTER fetching
            conn.commit()

        if not results:
            return []

        # Convert to Job objects
        jobs = []
        for row in results:
            job_dict = dict(zip(columns, row))
            jobs.append(Job(**job_dict))

        self.logger.info(f"Claimed {len(jobs)} jobs by {worker_id}")

        # Set the claiming thread's queue reference
        import threading

        try:
            threading.current_thread()._queuack_queue = self
        except Exception:
            pass

        return jobs

    def ack(
        self,
        job_id: str,
        result: Any = None,
        error: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        """
        Acknowledge job completion.

        Args:
            job_id: Job ID to acknowledge
            result: Result to store (will be pickled)
            error: Error message if job failed
            worker_id: Worker ID for ownership validation

        If error is provided, job is retried (if attempts < max_attempts)
        or moved to failed status.
        """
        # If caller provided a worker_id, enforce ownership
        if worker_id is not None:
            with self.connection_context() as conn:
                current = conn.execute(
                    "SELECT claimed_by, status FROM jobs WHERE id = ?",
                    [job_id],
                ).fetchone()
                conn.commit()
                if current is None:
                    raise ValueError(f"Job {job_id} not found")
                claimed_by, status = current
                if claimed_by != worker_id:
                    raise ValueError(
                        f"Worker {worker_id} attempted to ack job {job_id[:8]} but it is claimed by {claimed_by}"
                    )

        now = datetime.now()

        try:
            if error:
                # Failed - check if should retry
                with self.connection_context() as conn:
                    job = conn.execute(
                        """
                        SELECT attempts, max_attempts FROM jobs WHERE id = ?
                    """,
                        [job_id],
                    ).fetchone()
                    conn.commit()

                if job and job[0] < job[1]:
                    # Retry: move back to pending
                    with self.connection_context() as conn:
                        conn.execute(
                            """
                            UPDATE jobs
                            SET
                                status = 'pending',
                                error = ?,
                                claimed_at = NULL,
                                claimed_by = NULL
                            WHERE id = ?
                        """,
                            [error, job_id],
                        )
                        conn.commit()

                    self.logger.info(
                        f"Job {job_id[:8]} failed (attempt {job[0]}/{job[1]}), requeued"
                    )
                else:
                    # Max attempts reached: move to failed
                    with self.connection_context() as conn:
                        conn.execute(
                            """
                            UPDATE jobs
                            SET
                                status = 'failed',
                                completed_at = ?,
                                error = ?
                            WHERE id = ?
                        """,
                            [now, error, job_id],
                        )
                        conn.commit()

                    self.logger.error(f"Job {job_id[:8]} failed permanently: {error}")

                    # Propagate permanent failure to descendants
                    try:
                        # Iteratively propagate SKIPPED to transitive descendants
                        with self.connection_context() as conn:
                            while True:
                                updated = conn.execute(
                                    """
                                    WITH RECURSIVE descendants(child_id) AS (
                                        SELECT child_job_id FROM job_dependencies WHERE parent_job_id = ?
                                        UNION ALL
                                        SELECT jd.child_job_id FROM job_dependencies jd
                                        JOIN descendants d ON jd.parent_job_id = d.child_id
                                    ), dlist AS (
                                        SELECT DISTINCT child_id AS id FROM descendants
                                    ), parents AS (
                                        SELECT
                                            child.id AS id,
                                            child.dependency_mode AS dependency_mode,
                                            SUM(CASE WHEN pj.status NOT IN ('failed','skipped') THEN 1 ELSE 0 END) AS healthy_parents,
                                            COUNT(*) AS parent_count
                                        FROM dlist
                                        JOIN jobs child ON child.id = dlist.id
                                        JOIN job_dependencies jd ON jd.child_job_id = child.id
                                        JOIN jobs pj ON pj.id = jd.parent_job_id
                                        GROUP BY child.id, child.dependency_mode
                                    ), should_skip AS (
                                        SELECT
                                            id,
                                            CASE
                                                WHEN dependency_mode = 'all' AND healthy_parents < parent_count THEN 1
                                                WHEN dependency_mode = 'any' AND parent_count > 0 AND healthy_parents = 0 THEN 1
                                                ELSE 0
                                            END AS skip_flag
                                        FROM parents
                                    )
                                    UPDATE jobs
                                    SET
                                        status = 'skipped',
                                        skipped_at = ?,
                                        skip_reason = ?,
                                        skipped_by = ?,
                                        attempts = max_attempts,
                                        completed_at = ?
                                    FROM should_skip ss
                                    WHERE jobs.id = ss.id
                                    AND ss.skip_flag = 1
                                    AND jobs.status NOT IN ('done','failed','skipped')
                                    RETURNING jobs.id
                                """,
                                    [
                                        job_id,
                                        now,
                                        f"parent_failed:{job_id}",
                                        "queuack",
                                        now,
                                    ],
                                ).fetchall()
                                conn.commit()

                                if not updated:
                                    break

                        self.logger.info(
                            f"Marked descendants of {job_id[:8]} as SKIPPED"
                        )
                    except Exception as e:
                        self.logger.exception(
                            f"Error propagating skipped state for {job_id[:8]}: {e}"
                        )
                        # Still commit what we have

            else:
                # Success
                result_bytes = pickle.dumps(result) if result is not None else None

                with self.connection_context() as conn:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET
                            status = 'done',
                            completed_at = ?,
                            result = ?
                        WHERE id = ?
                    """,
                        [now, result_bytes, job_id],
                    )
                    conn.commit()

                self.logger.info(f"Job {job_id[:8]} completed successfully")

        except Exception:
            # Rollback on any error
            raise

    def nack(self, job_id: str, requeue: bool = True):
        """
        Negative acknowledge (job failed, but don't want to store error).

        Args:
            job_id: Job ID
            requeue: If True, move back to pending (default)
        """
        if requeue:
            with self.connection_context() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET
                        status = 'pending',
                        claimed_at = NULL,
                        claimed_by = NULL
                    WHERE id = ?
                """,
                    [job_id],
                )
                conn.commit()
            self.logger.info(f"Job {job_id[:8]} requeued")
        else:
            self.ack(job_id, error="Negative acknowledged without requeue")

    # ========================================================================
    # Monitoring & Introspection
    # ========================================================================

    def stats(self, queue: str = None) -> Dict[str, int]:
        """Get queue statistics."""
        if self._closed:
            raise Exception("Queue closed")

        queue = queue or self.default_queue

        with self.connection_context() as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM jobs
                WHERE queue = ?
                GROUP BY status
            """,
                [queue],
            )

            # CRITICAL FIX: Fetch BEFORE commit
            results = cursor.fetchall()

            # Commit AFTER fetching
            conn.commit()

        stats = {row[0]: row[1] for row in results}
        stats.setdefault("pending", 0)
        stats.setdefault("claimed", 0)
        stats.setdefault("done", 0)
        stats.setdefault("failed", 0)
        stats.setdefault("delayed", 0)

        return stats

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        with self.connection_context() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM jobs WHERE id = ?
            """,
                [job_id],
            )

            # CRITICAL FIX: Fetch BEFORE commit
            result = cursor.fetchone()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Commit AFTER fetching
            conn.commit()

        if result is None:
            return None

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
        with self.connection_context() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM dead_letter_queue
                ORDER BY completed_at DESC
                LIMIT ?
            """,
                [limit],
            )

            # CRITICAL FIX: Fetch BEFORE commit
            results = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Commit AFTER fetching
            conn.commit()

        jobs = []
        for row in results:
            job_dict = dict(zip(columns, row))
            jobs.append(Job(**job_dict))

        return jobs

    def purge(
        self, queue: str = None, status: str = "done", older_than_hours: int = 24
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

        with self.connection_context() as conn:
            if queue:
                # Count first, then delete
                count_result = conn.execute(
                    """
                    SELECT COUNT(*) FROM jobs
                    WHERE queue = ? AND status = ? AND created_at < ?
                """,
                    [queue, status, cutoff],
                ).fetchone()

                count = count_result[0] if count_result else 0

                if count > 0:
                    conn.execute(
                        """
                        DELETE FROM jobs
                        WHERE queue = ? AND status = ? AND created_at < ?
                    """,
                        [queue, status, cutoff],
                    )
            else:
                # Count first, then delete
                count_result = conn.execute(
                    """
                    SELECT COUNT(*) FROM jobs
                    WHERE status = ? AND created_at < ?
                """,
                    [status, cutoff],
                ).fetchone()

                count = count_result[0] if count_result else 0

                if count > 0:
                    conn.execute(
                        """
                        DELETE FROM jobs
                        WHERE status = ? AND created_at < ?
                    """,
                        [status, cutoff],
                    )

            conn.commit()

        self.logger.info(f"Purged {count} {status} jobs older than {older_than_hours}h")

        return count

    # ========================================================================
    # Helpers
    # ========================================================================

    def _generate_worker_id(self) -> str:
        """Generate unique worker identifier."""
        import os
        import socket
        import uuid

        # Use UUID for guaranteed uniqueness across concurrent tests
        return f"{socket.gethostname()}-{os.getpid()}-{str(uuid.uuid4())[:8]}"

    def close(self):
        """Close database connections and stop workers."""
        if self._closed:
            return

        self._closed = True

        # Stop workers first if they exist
        if self._worker_pool is not None:
            self.stop_workers()

        # Close the current thread's connection
        if not self._conn_pool._use_shared_memory:
            self._conn_pool.close_current()

    def dag(
        self,
        name: str,
        description: str = None,
        validate: bool = True,
        fail_fast: bool = True,
    ) -> DAGContext:
        """
        Create a DAG context manager.

        Args:
            name: DAG name
            description: Optional description
            validate: Validate DAG before submission
            fail_fast: Raise immediately on validation errors

        Returns:
            DAGContext manager

        Example:
            with queue.dag("etl") as dag:
                extract = dag.enqueue(extract_data, name="extract")
                transform = dag.enqueue(
                    transform_data,
                    depends_on="extract",
                    name="transform"
                )
        """
        return DAGContext(
            self,
            name,
            description=description,
            validate_on_exit=validate,
            fail_fast=fail_fast,
        )

    def create_dag(
        self,
        name: str,
        description: str = None,
        validate: bool = True,
        fail_fast: bool = True,
    ) -> DAG:
        """Create a new DAG (recommended API).

        Example:
            dag = queue.create_dag("etl")
            extract = dag.add_job(extract_data, name="extract")
            dag.submit()

        Returns:
            DAG instance
        """
        from .dag import DAG

        return DAG(
            name=name,
            queue=self,
            description=description,
            validate=validate,
            fail_fast=fail_fast,
        )


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
        max_jobs_in_flight: int = None,
        batch_size: int = 5,
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
        self.batch_size = batch_size
        self.should_stop = False
        self.jobs_in_flight = 0

        # Use queue's logger
        self.logger = queue.logger

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
        self.logger.info(f"Worker {self.worker_id} received shutdown signal")
        self.should_stop = True

    def run(self, poll_interval: float = DEFAULT_POLL_TIMEOUT):
        """
        Main worker loop.

        Args:
            poll_interval: Seconds to wait between polls when queue empty
        """
        # If tests request fast mode, use a tighter poll interval to
        # improve responsiveness under CPU contention (pytest-xdist).
        try:
            fast_mode = bool(int(os.getenv("QUEUACK_FAST_TESTS", "0")))
        except Exception:
            fast_mode = False

        if fast_mode:
            poll_interval = min(poll_interval, 0.01)

        self.logger.info(
            f"Worker {self.worker_id} started "
            f"(concurrency={self.concurrency}, backpressure={self.max_jobs_in_flight})"
        )
        self.logger.info(
            f"Listening on queues (by priority): {[q[0] for q in self.queues]}"
        )

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

        # When asked to stop, do a short graceful drain to pick up any jobs
        # that became available during shutdown. Instead of a single fixed
        # sleep window, try a few consecutive empty polls to avoid flaky
        # test outcomes on loaded machines while still bounding total wait
        # by WORKER_DRAIN_SECONDS.
        drain_deadline = time.perf_counter() + WORKER_DRAIN_SECONDS
        empty_polls_allowed = 3
        empty_polls = 0

        while (
            time.perf_counter() < drain_deadline and empty_polls < empty_polls_allowed
        ):
            job = self._claim_next_job()
            if not job:
                empty_polls += 1
                time.sleep(poll_interval)
                continue
            empty_polls = 0
            processed += 1
            self._execute_job(job, processed)

        self.logger.info(
            f"Worker {self.worker_id} stopped (processed {processed} jobs)"
        )
        # Final short drain: attempt a few more claims in case jobs were
        # enqueued concurrently during shutdown; keep the same safety
        # timeout behavior as above.
        drain_deadline = time.perf_counter() + WORKER_DRAIN_SECONDS
        empty_polls = 0
        while (
            time.perf_counter() < drain_deadline and empty_polls < empty_polls_allowed
        ):
            job = self._claim_next_job()
            if not job:
                empty_polls += 1
                time.sleep(poll_interval)
                continue
            empty_polls = 0
            processed += 1
            self._execute_job(job, processed)

    def _run_concurrent(self, poll_interval: float):
        """Multi-threaded execution with backpressure."""
        import threading
        from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

        processed = 0
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {}

            while not self.should_stop or futures:
                # Backpressure: Stop claiming if too many jobs in flight
                if len(futures) < self.max_jobs_in_flight and not self.should_stop:
                    # Calculate how many jobs we can accept
                    capacity = self.max_jobs_in_flight - len(futures)
                    batch_size = min(self.batch_size, capacity)

                    try:
                        job = self._claim_next_job()
                    except Exception as e:
                        self.logger.warning(
                            f"Error claiming job in worker {self.worker_id}: {e}"
                        )
                        time.sleep(poll_interval)
                        continue

                    if job:
                        with lock:
                            processed += 1
                            job_num = processed

                        future = executor.submit(self._execute_job, job, job_num)
                        futures[future] = job.id

                # Process completed jobs
                if futures:
                    try:
                        # When stopping, wait for all futures without timeout
                        # When running, use poll_interval timeout
                        timeout = None if self.should_stop else poll_interval

                        # Iterate through completed futures
                        for future in as_completed(futures.keys(), timeout=timeout):
                            job_id = futures.pop(future)
                            try:
                                future.result()  # Raise any exceptions
                            except Exception as e:
                                self.logger.error(
                                    f"Executor error for {job_id[:8]}: {e}"
                                )
                    except TimeoutError:
                        # No jobs completed in this interval, continue polling
                        pass
                else:
                    time.sleep(poll_interval)

        self.logger.info(
            f"Worker {self.worker_id} stopped (processed {processed} jobs)"
        )

    def _claim_next_batch(self, count: int = None) -> List[Job]:
        """Claim batch of jobs from highest-priority queue."""
        if count is None:
            count = self.batch_size

        for queue_name, _ in self.queues:
            jobs = self.queue.claim_batch(
                count=count, queue=queue_name, worker_id=self.worker_id
            )
            if jobs:
                return jobs

        return []

    def _claim_next_job(self) -> Optional[Job]:
        """Claim next job from highest-priority queue with error handling."""
        for queue_name, _ in self.queues:
            try:
                job = self.queue.claim(queue=queue_name, worker_id=self.worker_id)
                if job:
                    return job
            except Exception as e:
                self.logger.debug(f"Failed to claim from queue {queue_name}: {e}")
                # Continue trying other queues rather than failing completely
                continue
        return None

    def _execute_job(self, job: Job, job_num: int):
        threading.current_thread()._queuack_queue = self.queue

        acked = False
        try:
            start_time = time.perf_counter()
            result = job.execute(logger=self.logger)
            duration = time.perf_counter() - start_time

            self.queue.ack(job.id, result=result, worker_id=self.worker_id)
            acked = True

            self.logger.info(
                f"✓ [{self.worker_id}] Job {job.id[:8]} completed in {duration:.2f}s (#{job_num})"
            )

        except Exception as e:
            if not acked:
                error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                try:
                    self.queue.ack(job.id, error=error_msg, worker_id=self.worker_id)
                except Exception as ack_error:
                    self.logger.error(
                        f"✗ Failed to ack job {job.id[:8]} after execution error. "
                        f"Original: {e}. Ack error: {ack_error}"
                    )

            self.logger.error(f"✗ [{self.worker_id}] Job {job.id[:8]} failed: {e}")


class ConnectionPool:
    """Thread-safe connection pool for DuckDB.

    Manages thread-local connections. Supports a single shared connection
    when using an in-memory database path (":memory:") because separate
    connections to ":memory:" do not share schema/data.

    CRITICAL: DuckDB connections are NOT thread-safe. For :memory: databases,
    we use a shared connection but protect it with a lock to serialize access.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

        # Detect in-memory DB usage
        self._use_shared_memory = self.db_path == ":memory:"

        # For :memory:, we'll create the connection during schema init
        # and store it here. For file DBs, this stays None.
        self._global_conn: Optional[duckdb.DuckDBPyConnection] = None

        # CRITICAL FIX: Lock to serialize access to shared connection
        # DuckDB connections are NOT thread-safe, so we must synchronize access
        self._connection_lock = threading.Lock()

        # Global lock to prevent connections during schema init
        self._ready = threading.Event()
        self._ready.set()  # Will be cleared during schema init

    def wait_until_ready(self):
        """Block until the database is ready (schema initialized)."""
        self._ready.wait()

    def mark_initializing(self):
        """Mark database as initializing (blocks new connections)."""
        self._ready.clear()

    def mark_ready(self):
        """Mark database as ready (allows new connections)."""
        self._ready.set()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create a thread-local connection.

        If using a shared in-memory DB (':memory:'), return the single
        global connection so schema/data are visible to everyone.

        CRITICAL FIX: For :memory:, _global_conn is created during schema
        initialization and must exist before this is called.
        """
        # Wait until schema is initialized
        self._ready.wait()

        if self._use_shared_memory:
            # Return the pre-created shared connection
            # This must have been set during _init_schema()
            if self._global_conn is None:
                raise RuntimeError(
                    "Internal error: shared memory connection not initialized. "
                    "This should have been created during schema initialization."
                )
            return self._global_conn

        # Otherwise, use a thread-local connection (file-backed DB case)
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = duckdb.connect(self.db_path)
        return self._local.conn

    def set_global_connection(self, conn: duckdb.DuckDBPyConnection):
        """Set the global shared connection (used for :memory: during init).

        This should only be called once during schema initialization.
        """
        if not self._use_shared_memory:
            raise RuntimeError(
                "set_global_connection should only be used for :memory: databases"
            )

        if self._global_conn is not None:
            raise RuntimeError("Global connection already set")

        self._global_conn = conn

    def connection_context(self):
        """Get a connection context manager that handles locking."""
        return _ConnectionContext(self)

    def close_current(self):
        """Close the current thread's connection or the global shared one."""
        try:
            if self._use_shared_memory:
                if self._global_conn is not None:
                    try:
                        self._global_conn.close()
                    except Exception:
                        pass
                    self._global_conn = None
            else:
                if hasattr(self._local, "conn") and self._local.conn is not None:
                    try:
                        self._local.conn.close()
                    except Exception:
                        pass
                    self._local.conn = None
        except Exception:
            # be defensive — closing shouldn't raise to caller
            pass


class _ConnectionContext:
    """Context manager for thread-safe database operations."""

    def __init__(self, pool: "ConnectionPool"):
        self.pool = pool
        self.conn = None

    def __enter__(self):
        # For shared memory connections, acquire the lock first
        if self.pool._use_shared_memory:
            self.pool._connection_lock.acquire()

        self.conn = self.pool.get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Release the lock if we acquired it
        if self.pool._use_shared_memory:
            self.pool._connection_lock.release()

        # Don't close the connection - it's managed by the pool


class WorkerPool:
    def __init__(self, queue: DuckQueue, num_workers: int = 4, concurrency: int = 1):
        self.queue = queue
        self.num_workers = num_workers
        self.concurrency = concurrency
        self.workers = []
        self.threads = []
        self.running = False
        self.logger = queue.logger

    def start(self):
        """Start workers in background threads."""
        self.running = True

        for i in range(self.num_workers):
            worker = Worker(
                self.queue, worker_id=f"worker-{i}", concurrency=self.concurrency
            )
            self.workers.append(worker)

            thread = threading.Thread(
                target=worker.run,
                args=(self.queue._poll_timeout,),  # poll_interval from queue
                daemon=True,  # Dies when main thread exits
                name=f"WorkerThread-{i}",
            )
            thread.start()
            self.threads.append(thread)

        self.logger.info(f"WorkerPool started with {self.num_workers} workers")

    def stop(self, timeout: int = 30):
        """Gracefully stop all workers."""
        for worker in self.workers:
            worker.should_stop = True

        for thread in self.threads:
            thread.join(timeout=timeout)

        self.logger.info("WorkerPool stopped")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# ============================================================================
# Convenience Decorators
# ============================================================================


def job(
    queue_instance: DuckQueue,
    queue: str = "default",
    priority: int = 50,
    delay_seconds: int = 0,
    max_attempts: int = 3,
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
                max_attempts=max_attempts,
            )

        func.delay = delay
        return func

    return decorator
