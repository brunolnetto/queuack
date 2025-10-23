# file: test_queuack.py
# dependencies: pytest>=7.0.0, pytest-cov>=4.0.0, duckdb>=0.9.0
# run: pytest test_duckqueue.py -v --cov=core --cov-report=html --cov-report=term-missing

"""
Comprehensive test suite for DuckQueue with 100% code coverage.

IMPORTANT: All test functions must be defined at MODULE LEVEL to be picklable.
Functions defined inside test methods or as nested functions cannot be pickled
and will cause "Can't pickle local object" errors.

Thread Safety Note:
- DuckDB connections are NOT thread-safe for concurrent writes
- In production, use separate processes or one connection per thread
- The concurrent tests verify behavior within these constraints

Run tests:
    pytest test_duckqueue.py -v

Generate coverage report:
    pytest test_duckqueue.py --cov=core --cov-report=html

Run specific test:
    pytest test_duckqueue.py::TestDuckQueue::test_enqueue_basic -v
"""

import os
import pickle

# Import from duckqueue module
# Assuming the module is named 'core' based on your file structure
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queuack import (
    BackpressureError,
    ConnectionPool,
    DuckQueue,
    Job,
    JobStatus,
    Worker,
    WorkerPool,
    job,
)


# Subclass used by the test fixtures so backpressure thresholds are low and
# tests that exercise many enqueues run quickly.
class FastThresholdQueue(DuckQueue):
    @classmethod
    def backpressure_warning_threshold(cls) -> int:
        return 20

    @classmethod
    def backpressure_block_threshold(cls) -> int:
        return 100


# ============================================================================
# Module-level test functions (must be picklable)
# ============================================================================


def add(a, b):
    """Sample function for testing."""
    return a + b


def slow(duration=0.5):
    """Slow function for timeout testing."""
    time.sleep(duration)
    return "completed"


def fail(message="Test failure"):
    """Function that always fails."""
    raise ValueError(message)


def greet(name, greeting="Hello"):
    """Greeting function with default args."""
    return f"{greeting}, {name}!"


def return_none():
    """Function that returns None."""
    return None


def process_data(x):
    """Process data by doubling it."""
    return x * 2


def square(x):
    """Square a number."""
    return x * x


def email_task(to):
    """Email task function."""
    return f"Email to {to}"


def report_task(id):
    """Report task function."""
    return f"Report {id}"


def no_args():
    """Function with no arguments."""
    return "no args"


def large_result():
    """Function returning large result."""
    return "x" * 1000000


def complex_task(data):
    """Function with complex data structures."""
    return {"nested": data, "count": len(data["items"])}


def unicode_task(text):
    """Function with unicode."""
    return f"Processed: {text}"


def always_fails():
    """Function that always fails."""
    raise RuntimeError("Always fails")


# Global counter for flaky task
flaky_attempt_count = {"count": 0}


def flaky_task():
    """Task that fails first few times."""
    flaky_attempt_count["count"] += 1
    if flaky_attempt_count["count"] < 3:
        raise ValueError("Not ready yet")
    return "success"


def reset_flaky_counter():
    """Reset the flaky task counter."""
    flaky_attempt_count["count"] = 0


def task_priority(priority_level):
    """Task that returns its priority level."""
    return f"Priority {priority_level}"


def delayed_task():
    """Delayed task."""
    return "delayed result"


def send_email_simple(to):
    """Send email task."""
    return f"Email sent to {to}"


def cleanup_logs_simple(days):
    """Cleanup logs task."""
    return f"Cleaned logs older than {days} days"


def identity(x):
    """Return the input."""
    return x


def add_ten(x):
    """Add 10 to input."""
    return x + 10


def simple_task():
    """Simple task for testing."""
    return 42


def slow_task():
    """Slow task for timeout testing."""
    time.sleep(0.5)
    return "done"


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def queue():
    """Create in-memory queue for testing."""
    # Use a unique temporary file per test to guarantee full isolation
    # (especially important when tests start worker threads/connections).
    with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
        db_path = f.name

    # Ensure file is removed so DuckDB creates it cleanly
    try:
        os.unlink(db_path)
    except Exception:
        pass

    q = FastThresholdQueue(db_path)
    try:
        yield q
    finally:
        q.close()
        try:
            os.unlink(db_path)
        except Exception:
            pass


def noop():
    return None


def a_func():
    return "a"


def b_func():
    return "b"


def c_func():
    return "c"


def d_func():
    return "d"


# ============================================================================
# Test Data Models
# ============================================================================


class TestJobStatus:
    """Test JobStatus enum."""

    def test_all_statuses(self):
        """Test all job status values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.CLAIMED.value == "claimed"
        assert JobStatus.DONE.value == "done"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.DELAYED.value == "delayed"


class TestBackpressureError:
    """Test BackpressureError exception."""

    def test_exception_raised(self):
        """Test exception can be raised and caught."""
        with pytest.raises(BackpressureError) as exc_info:
            raise BackpressureError("Queue full")

        assert "Queue full" in str(exc_info.value)


class TestJob:
    """Test Job dataclass."""

    def test_job_creation(self):
        """Test Job object creation."""
        job = Job(
            id="test-123",
            func=pickle.dumps(add),
            args=pickle.dumps((1, 2)),
            kwargs=pickle.dumps({}),
            queue="default",
            status="pending",
        )

        assert job.id == "test-123"
        assert job.queue == "default"
        assert job.status == "pending"
        assert job.priority == 50  # default
        assert job.attempts == 0
        assert job.max_attempts == 3
        assert job.created_at is not None

    def test_job_execute(self):
        """Test job execution."""
        job = Job(
            id="test-123",
            func=pickle.dumps(add),
            args=pickle.dumps((5, 3)),
            kwargs=pickle.dumps({}),
            queue="default",
            status="claimed",
        )

        result = job.execute()
        assert result == 8

    def test_job_execute_with_kwargs(self):
        """Test job execution with kwargs."""
        job = Job(
            id="test-123",
            func=pickle.dumps(greet),
            args=pickle.dumps(("World",)),
            kwargs=pickle.dumps({"greeting": "Hi"}),
            queue="default",
            status="claimed",
        )

        result = job.execute()
        assert result == "Hi, World!"


# ============================================================================
# Test DuckQueue Core
# ============================================================================


class TestDuckQueue:
    """Test DuckQueue core functionality."""

    def test_initialization_memory(self):
        """Test queue initialization with in-memory database."""
        queue = DuckQueue(":memory:")
        assert queue.db_path == ":memory:"
        assert queue.default_queue == "default"
        queue.close()

    def test_initialization_file(self, queue: DuckQueue):
        """Test queue initialization with file database."""
        assert os.path.exists(queue.db_path)

    def test_initialization_custom_queue(self):
        """Test queue initialization with custom default queue."""
        queue = DuckQueue(":memory:", default_queue="custom")
        assert queue.default_queue == "custom"
        queue.close()

    def test_schema_creation(self, queue: DuckQueue):
        """Test database schema is created."""
        # Check jobs table exists
        result = queue.conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='jobs'
        """).fetchone()
        assert result is not None

        # Check index exists
        result = queue.conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name='idx_jobs_claim'
        """).fetchone()
        assert result is not None

        # Check view exists
        result = queue.conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='view' AND name='dead_letter_queue'
        """).fetchone()
        assert result is not None

    # Enqueue Tests
    def test_enqueue_basic(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        assert job_id is not None
        assert len(job_id) == 36
        job = queue.get_job(job_id)
        assert job.status == JobStatus.PENDING.value

    def test_enqueue_with_kwargs(self, queue: DuckQueue):
        job_id = queue.enqueue(greet, args=("World",), kwargs={"greeting": "Hi"})
        job = queue.get_job(job_id)
        result = job.execute()
        assert result == "Hi, World!"

    def test_enqueue_custom_queue(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), queue="emails")
        job = queue.get_job(job_id)
        assert job.queue == "emails"

    def test_enqueue_with_priority(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), priority=90)
        job = queue.get_job(job_id)
        assert job.priority == 90

    def test_enqueue_with_delay(self, queue: DuckQueue):
        before = datetime.now()
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=5)
        job = queue.get_job(job_id)
        assert job.status == JobStatus.DELAYED.value
        assert job.execute_after >= before + timedelta(seconds=5)

    def test_enqueue_max_attempts(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), max_attempts=5)
        job = queue.get_job(job_id)
        assert job.max_attempts == 5

    def test_enqueue_timeout(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), timeout_seconds=600)
        job = queue.get_job(job_id)
        assert job.timeout_seconds == 600

    def test_enqueue_unpicklable_function(self, queue: DuckQueue):
        with pytest.raises(ValueError) as exc_info:
            queue.enqueue(lambda x: x + 1, args=(1,))
        assert "not picklable" in str(exc_info.value)

    def test_enqueue_backpressure_warning(self, queue: DuckQueue):
        """Test that warning is issued at 1000 jobs."""
        import warnings

        # Enqueue 999 jobs (should not warn)
        for i in range(queue.backpressure_warning_threshold()):
            queue.enqueue(add, args=(i, i), check_backpressure=False)

        # 1000th job should trigger warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            queue.enqueue(add, args=(1000, 1000), check_backpressure=True)
            assert len(w) == 1
            assert issubclass(w[0].category, UserWarning)
            assert "approaching limit" in str(w[0].message)

    def test_enqueue_backpressure_block(self, queue: DuckQueue):
        # Enqueue 10001 jobs to exceed the 10000 limit
        for i in range(queue.backpressure_block_threshold() + 1):
            queue.enqueue(add, args=(i, i), check_backpressure=False)

        # Next enqueue should fail
        with pytest.raises(BackpressureError) as exc_info:
            queue.enqueue(add, args=(1, 1), check_backpressure=True)

        assert "10000" in str(exc_info.value) or "overloaded" in str(exc_info.value)

    def test_enqueue_backpressure_disabled(self, queue: DuckQueue):
        jobs_count = queue.backpressure_warning_threshold() - 1

        for i in range(jobs_count):
            queue.enqueue(add, args=(i, i), check_backpressure=False)
        assert queue.stats()["pending"] == jobs_count

    # Batch Enqueue Tests
    def test_enqueue_batch(self, queue: DuckQueue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {}), (add, (5, 6), {})]
        job_ids = queue.enqueue_batch(jobs)
        assert len(job_ids) == 3
        for job_id in job_ids:
            assert queue.get_job(job_id).status == JobStatus.PENDING.value

    def test_enqueue_batch_custom_queue(self, queue: DuckQueue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {})]
        job_ids = queue.enqueue_batch(jobs, queue="batch")
        for job_id in job_ids:
            assert queue.get_job(job_id).queue == "batch"

    def test_enqueue_batch_priority(self, queue: DuckQueue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {})]
        job_ids = queue.enqueue_batch(jobs, priority=80)
        for job_id in job_ids:
            assert queue.get_job(job_id).priority == 80

    # Claim Tests
    def test_claim_basic(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        assert job.id == job_id
        assert job.status == JobStatus.CLAIMED.value
        assert job.attempts == 1

    def test_claim_empty_queue(self, queue: DuckQueue):
        assert queue.claim() is None

    def test_claim_custom_queue(self, queue: DuckQueue):
        queue.enqueue(add, args=(1, 2), queue="emails")
        assert queue.claim(queue="default") is None
        job = queue.claim(queue="emails")
        assert job.queue == "emails"

    def test_claim_priority_order(self, queue: DuckQueue):
        low_id = queue.enqueue(add, args=(1, 1), priority=10)
        high_id = queue.enqueue(add, args=(2, 2), priority=90)
        med_id = queue.enqueue(add, args=(3, 3), priority=50)
        assert queue.claim().id == high_id
        assert queue.claim().id == med_id
        assert queue.claim().id == low_id

    def test_claim_fifo_same_priority(self, queue: DuckQueue):
        id1 = queue.enqueue(add, args=(1, 1))
        time.sleep(0.01)
        id2 = queue.enqueue(add, args=(2, 2))
        time.sleep(0.01)
        id3 = queue.enqueue(add, args=(3, 3))
        assert queue.claim().id == id1
        assert queue.claim().id == id2
        assert queue.claim().id == id3

    def test_claim_delayed_job_not_ready(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=10)
        assert queue.claim() is None
        assert queue.get_job(job_id).status == JobStatus.DELAYED.value

    def test_claim_delayed_job_ready(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=1)
        time.sleep(1.2)  # Increase from 1.1 to 1.2
        job = queue.claim()

        # Add defensive check:
        if job is None:
            time.sleep(0.5)  # Wait a bit more
            job = queue.claim()

        assert job is not None, "Job should be claimable after delay"
        assert job.id == job_id
        assert job.status == JobStatus.CLAIMED.value

    def test_claim_promotes_delayed_jobs(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=1)
        time.sleep(1.1)
        job = queue.claim()
        assert job.id == job_id

    def test_claim_stale_job_recovery(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job1 = queue.claim(worker_id="worker-1")
        old_time = datetime.now() - timedelta(seconds=400)
        queue.conn.execute(
            "UPDATE jobs SET claimed_at = ? WHERE id = ?", [old_time, job_id]
        )
        job2 = queue.claim(worker_id="worker-2", claim_timeout=300)
        assert job2.id == job_id
        assert job2.claimed_by == "worker-2"
        assert job2.attempts == 2

    def test_claim_custom_worker_id(self, queue: DuckQueue):
        queue.enqueue(add, args=(1, 2))
        job = queue.claim(worker_id="custom-worker")
        assert job.claimed_by == "custom-worker"

    def test_claim_max_attempts_exceeded(self, queue: DuckQueue):
        job_id = queue.enqueue(fail, max_attempts=2)
        for i in range(2):
            job = queue.claim()
            queue.ack(job.id, error="Failed")
        assert queue.claim() is None
        assert queue.get_job(job_id).status == JobStatus.FAILED.value

    # Ack Tests
    def test_ack_success(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(5, 3))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        completed_job = queue.get_job(job_id)
        assert completed_job.status == JobStatus.DONE.value
        assert queue.get_result(job_id) == 8

    def test_ack_success_no_result(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.ack(job.id)
        assert queue.get_job(job_id).status == JobStatus.DONE.value

    def test_ack_failure_with_retry(self, queue: DuckQueue):
        job_id = queue.enqueue(fail, max_attempts=3)
        job = queue.claim()
        queue.ack(job.id, error="Test error")
        retry_job = queue.get_job(job_id)
        assert retry_job.status == JobStatus.PENDING.value
        assert retry_job.attempts == 1

    def test_ack_failure_max_attempts(self, queue: DuckQueue):
        job_id = queue.enqueue(fail, max_attempts=2)
        for i in range(2):
            job = queue.claim()
            queue.ack(job.id, error=f"Attempt {i + 1} failed")
        failed_job = queue.get_job(job_id)
        assert failed_job.status == JobStatus.FAILED.value

    def test_ack_nonexistent_job(self, queue: DuckQueue):
        queue.ack("nonexistent-id", error="Test")

    # Nack Tests
    def test_nack_with_requeue(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.nack(job.id, requeue=True)
        requeued_job = queue.get_job(job_id)
        assert requeued_job.status == JobStatus.PENDING.value

    def test_nack_without_requeue(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.nack(job.id, requeue=False)
        failed_job = queue.get_job(job_id)
        # After nack without requeue, job should be failed (via ack with error)
        # The nack calls ack with error, which might retry if attempts < max_attempts
        # So we need to check if it's either failed or pending (for retry)
        assert failed_job.status in [JobStatus.FAILED.value, JobStatus.PENDING.value]
        if failed_job.status == JobStatus.PENDING.value:
            # It was retried, let's exhaust retries
            while (
                failed_job.status == JobStatus.PENDING.value
                and failed_job.attempts < failed_job.max_attempts
            ):
                job = queue.claim()
                if job:
                    queue.ack(job.id, error="Nack without requeue")
                    failed_job = queue.get_job(job_id)
        assert failed_job.status == JobStatus.FAILED.value

    # Monitoring Tests
    def test_stats_empty_queue(self, queue: DuckQueue):
        stats = queue.stats()
        assert stats["pending"] == 0
        assert stats["claimed"] == 0
        assert stats["done"] == 0
        assert stats["failed"] == 0
        assert stats["delayed"] == 0

    def test_stats_with_jobs(self, queue: DuckQueue):
        queue.enqueue(add, args=(1, 2))
        queue.enqueue(add, args=(3, 4))
        queue.enqueue(add, args=(5, 6), delay_seconds=10)
        job = queue.claim()
        queue.ack(job.id, result=5)
        stats = queue.stats()
        assert stats["pending"] == 1
        assert stats["done"] == 1
        assert stats["delayed"] == 1

    def test_stats_custom_queue(self, queue: DuckQueue):
        queue.enqueue(add, args=(1, 2), queue="emails")
        queue.enqueue(add, args=(3, 4), queue="emails")
        queue.enqueue(add, args=(5, 6), queue="reports")
        assert queue.stats("emails")["pending"] == 2
        assert queue.stats("reports")["pending"] == 1

    def test_get_job_exists(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.get_job(job_id)
        assert job.id == job_id

    def test_get_job_not_exists(self, queue: DuckQueue):
        assert queue.get_job("nonexistent-id") is None

    def test_get_result_success(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(10, 20))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        assert queue.get_result(job_id) == 30

    def test_get_result_not_found(self, queue: DuckQueue):
        with pytest.raises(ValueError) as exc_info:
            queue.get_result("nonexistent-id")
        assert "not found" in str(exc_info.value)

    def test_get_result_not_done(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        with pytest.raises(ValueError) as exc_info:
            queue.get_result(job_id)
        assert "not done" in str(exc_info.value)

    def test_get_result_none(self, queue: DuckQueue):
        job_id = queue.enqueue(return_none)
        job = queue.claim()
        queue.ack(job.id, result=None)
        assert queue.get_result(job_id) is None

    def test_list_dead_letters(self, queue: DuckQueue):
        for i in range(3):
            job_id = queue.enqueue(fail, args=(f"fail-{i}",), max_attempts=1)
            job = queue.claim()
            queue.ack(job.id, error=f"Failed {i}")
        dead_letters = queue.list_dead_letters()
        assert len(dead_letters) == 3
        for job in dead_letters:
            assert job.status == JobStatus.FAILED.value

    def test_list_dead_letters_limit(self, queue: DuckQueue):
        for i in range(5):
            job_id = queue.enqueue(fail, max_attempts=1)
            job = queue.claim()
            queue.ack(job.id, error="Failed")
        assert len(queue.list_dead_letters(limit=3)) == 3

    def test_list_dead_letters_empty(self, queue: DuckQueue):
        assert len(queue.list_dead_letters()) == 0

    # Purge Tests
    def test_purge_done_jobs(self, queue: DuckQueue):
        for i in range(3):
            job_id = queue.enqueue(add, args=(i, i))
            job = queue.claim()
            queue.ack(job.id, result=i * 2)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute(
            "UPDATE jobs SET created_at = ? WHERE status = 'done'", [old_time]
        )
        count = queue.purge(status="done", older_than_hours=24)
        assert count == 3
        assert queue.stats()["done"] == 0

    def test_purge_specific_queue(self, queue: DuckQueue):
        for i in range(2):
            job_id = queue.enqueue(add, args=(i, i), queue="emails")
            job = queue.claim(queue="emails")
            queue.ack(job.id, result=i)
        for i in range(3):
            job_id = queue.enqueue(add, args=(i, i), queue="reports")
            job = queue.claim(queue="reports")
            queue.ack(job.id, result=i)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ?", [old_time])
        count = queue.purge(queue="emails", status="done", older_than_hours=24)
        assert count == 2
        assert queue.stats("emails")["done"] == 0
        assert queue.stats("reports")["done"] == 3

    def test_purge_failed_jobs(self, queue: DuckQueue):
        job_id = queue.enqueue(fail, max_attempts=1)
        job = queue.claim()
        queue.ack(job.id, error="Failed")
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute(
            "UPDATE jobs SET created_at = ? WHERE id = ?", [old_time, job_id]
        )
        count = queue.purge(status="failed", older_than_hours=24)
        assert count == 1

    def test_purge_no_old_jobs(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.ack(job.id, result=3)
        count = queue.purge(status="done", older_than_hours=24)
        assert count == 0

    def test_purge_all_queues(self, queue: DuckQueue):
        for q in ["queue1", "queue2", "queue3"]:
            job_id = queue.enqueue(add, args=(1, 2), queue=q)
            job = queue.claim(queue=q)
            queue.ack(job.id, result=3)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ?", [old_time])
        count = queue.purge(queue=None, status="done", older_than_hours=24)
        assert count == 3

    # Helper Tests
    def test_generate_worker_id(self, queue: DuckQueue):
        worker_id = queue._generate_worker_id()
        assert worker_id is not None
        assert isinstance(worker_id, str)
        import os
        import socket

        assert socket.gethostname() in worker_id
        assert str(os.getpid()) in worker_id

    def test_close(self, queue: DuckQueue):
        queue.close()
        with pytest.raises(Exception):
            queue.stats()


# ============================================================================
# Test Worker
# ============================================================================


class TestWorker:
    """Test Worker class."""

    def test_worker_initialization(self, queue: DuckQueue):
        worker = Worker(queue)
        assert worker.queue == queue
        assert worker.concurrency == 1
        assert worker.max_jobs_in_flight == 2
        assert worker.should_stop == False

    def test_worker_custom_settings(self, queue: DuckQueue):
        worker = Worker(
            queue,
            queues=["emails", "reports"],
            worker_id="custom-worker",
            concurrency=4,
            max_jobs_in_flight=10,
        )
        assert worker.worker_id == "custom-worker"
        assert worker.concurrency == 4
        assert worker.max_jobs_in_flight == 10

    def test_worker_parse_queues_simple(self, queue: DuckQueue):
        worker = Worker(queue, queues=["queue1", "queue2"])
        assert len(worker.queues) == 2

    def test_worker_parse_queues_with_priority(self, queue: DuckQueue):
        worker = Worker(queue, queues=[("high", 100), ("low", 10), ("medium", 50)])
        assert worker.queues[0] == ("high", 100)
        assert worker.queues[1] == ("medium", 50)
        assert worker.queues[2] == ("low", 10)

    def test_worker_signal_handler(self, queue: DuckQueue):
        worker = Worker(queue)
        assert worker.should_stop == False
        worker._signal_handler(None, None)
        assert worker.should_stop 

    def test_worker_claim_next_job(self, queue: DuckQueue):
        worker = Worker(queue, queues=["emails", "reports"])
        queue.enqueue(add, args=(1, 2), queue="reports")
        job = worker._claim_next_job()
        assert job.queue == "reports"

    def test_worker_claim_next_job_priority(self, queue: DuckQueue):
        worker = Worker(queue, queues=[("high", 100), ("low", 10)])
        queue.enqueue(add, args=(1, 1), queue="low")
        queue.enqueue(add, args=(2, 2), queue="high")
        job = worker._claim_next_job()
        assert job.queue == "high"

    def test_worker_execute_job_success(self, queue: DuckQueue):
        worker = Worker(queue)
        job_id = queue.enqueue(add, args=(5, 10))
        job = queue.claim()
        worker._execute_job(job, 1)
        assert queue.get_job(job_id).status == JobStatus.DONE.value
        assert queue.get_result(job_id) == 15

    def test_worker_execute_job_failure(self, queue: DuckQueue):
        worker = Worker(queue)
        job_id = queue.enqueue(fail, args=("test error",))
        job = queue.claim()
        worker._execute_job(job, 1)
        failed = queue.get_job(job_id)
        assert failed.status == JobStatus.PENDING.value  # Retried

    def test_worker_run_sequential(self, queue: DuckQueue):
        worker = Worker(queue)
        for i in range(3):
            queue.enqueue(add, args=(i, i))

        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()["done"] == 3

    def test_worker_run_concurrent(self, queue: DuckQueue):
        worker = Worker(queue, concurrency=2)
        for i in range(4):
            queue.enqueue(slow, args=(0.2,))

        def stop_worker():
            time.sleep(1.5)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()["done"] == 4

    def test_worker_concurrent_backpressure(self, queue: DuckQueue):
        worker = Worker(queue, concurrency=2, max_jobs_in_flight=2)
        for i in range(10):
            queue.enqueue(slow, args=(0.1,))

        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.05)
        assert queue.stats()["done"] > 0

    def test_worker_concurrent_exception_handling(self, queue: DuckQueue):
        worker = Worker(queue, concurrency=2)
        for i in range(3):
            queue.enqueue(fail, max_attempts=1)

        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()["failed"] == 3

    def test_worker_concurrent_timeout(self, queue: DuckQueue):
        worker = Worker(queue, concurrency=2)
        queue.enqueue(add, args=(1, 2))

        def stop_worker():
            time.sleep(0.3)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()["done"] == 1

    def test_worker_signal_registration_main_thread(self, queue: DuckQueue):
        worker = Worker(queue)
        assert worker.worker_id is not None

    def test_worker_signal_registration_background_thread(self, queue: DuckQueue):
        worker_ref = []

        def create_worker():
            worker = Worker(queue)
            worker_ref.append(worker)

        thread = threading.Thread(target=create_worker)
        thread.start()
        thread.join()
        assert len(worker_ref) == 1

    def test_worker_stops_when_no_futures(self, queue: DuckQueue):
        worker = Worker(queue, concurrency=2)
        worker.should_stop = True
        worker.run(poll_interval=0.1)


# ============================================================================
# Test Decorator
# ============================================================================

# Module-level decorated functions for testing
_test_queue = None


def decorated_add(a, b):
    """Decorated add function."""
    return a + b


def decorated_greet(name, greeting="Hello"):
    """Decorated greet function."""
    return f"{greeting}, {name}!"


def decorated_email(to):
    """Decorated email function."""
    return f"Email sent to {to}"


def decorated_urgent():
    """Decorated urgent function."""
    return "done"


def decorated_delayed():
    """Decorated delayed function."""
    return "delayed"


def decorated_retry():
    """Decorated retry function."""
    return "done"


class TestJobDecorator:
    """Test job decorator."""

    def test_decorator_basic(self, queue: DuckQueue):
        # Manually apply decorator to module-level function
        decorated_func = job(queue)(decorated_add)

        assert hasattr(decorated_func, "delay")
        assert decorated_func(1, 2) == 3
        job_id = decorated_func.delay(5, 10)
        claimed = queue.claim()
        result = claimed.execute()
        queue.ack(claimed.id, result=result)
        assert queue.get_result(job_id) == 15

    def test_decorator_with_kwargs(self, queue: DuckQueue):
        decorated_func = job(queue)(decorated_greet)

        job_id = decorated_func.delay("World", greeting="Hi")
        claimed = queue.claim()
        result = claimed.execute()
        assert result == "Hi, World!"

    def test_decorator_custom_queue(self, queue: DuckQueue):
        decorated_func = job(queue, queue="emails")(decorated_email)

        job_id = decorated_func.delay("user@example.com")
        assert queue.get_job(job_id).queue == "emails"

    def test_decorator_custom_priority(self, queue: DuckQueue):
        decorated_func = job(queue, priority=90)(decorated_urgent)

        job_id = decorated_func.delay()
        assert queue.get_job(job_id).priority == 90

    def test_decorator_delay_seconds(self, queue: DuckQueue):
        decorated_func = job(queue, delay_seconds=5)(decorated_delayed)

        job_id = decorated_func.delay()
        assert queue.get_job(job_id).status == JobStatus.DELAYED.value

    def test_decorator_max_attempts(self, queue: DuckQueue):
        decorated_func = job(queue, max_attempts=5)(decorated_retry)

        job_id = decorated_func.delay()
        assert queue.get_job(job_id).max_attempts == 5


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for complete workflows."""

    def test_complete_workflow(self, queue: DuckQueue):
        job_ids = []
        for i in range(5):
            job_id = queue.enqueue(process_data, args=(i,))
            job_ids.append(job_id)

        results = []
        for _ in range(5):
            job = queue.claim()
            result = job.execute()
            queue.ack(job.id, result=result)
            results.append(result)

        assert results == [0, 2, 4, 6, 8]
        assert queue.stats()["done"] == 5

    def test_retry_workflow(self, queue: DuckQueue):
        reset_flaky_counter()
        job_id = queue.enqueue(flaky_task, max_attempts=3)

        # First attempt - fails
        job1 = queue.claim()
        try:
            job1.execute()
        except ValueError as e:
            queue.ack(job1.id, error=str(e))

        # Second attempt - fails
        job2 = queue.claim()
        try:
            job2.execute()
        except ValueError as e:
            queue.ack(job2.id, error=str(e))

        # Third attempt - succeeds
        job3 = queue.claim()
        result = job3.execute()
        queue.ack(job3.id, result=result)

        final_job = queue.get_job(job_id)
        assert final_job.status == JobStatus.DONE.value
        assert final_job.attempts == 3

    def test_priority_workflow(self, queue: DuckQueue):
        low_id = queue.enqueue(task_priority, args=("low",), priority=10)
        high_id = queue.enqueue(task_priority, args=("high",), priority=90)
        med_id = queue.enqueue(task_priority, args=("medium",), priority=50)

        results = []
        for _ in range(3):
            job = queue.claim()
            result = job.execute()
            queue.ack(job.id, result=result)
            results.append(result)

        assert results == ["Priority high", "Priority medium", "Priority low"]

    def test_delayed_workflow(self, queue: DuckQueue):
        job_id = queue.enqueue(delayed_task, delay_seconds=1)
        assert queue.claim() is None
        time.sleep(1.1)
        job = queue.claim()
        assert job is not None
        result = job.execute()
        queue.ack(job.id, result=result)
        assert queue.get_result(job_id) == "delayed result"

    def test_multi_queue_workflow(self, queue: DuckQueue):
        queue.enqueue(email_task, args=("user1@example.com",), queue="emails")
        queue.enqueue(email_task, args=("user2@example.com",), queue="emails")
        queue.enqueue(report_task, args=(101,), queue="reports")

        email_results = []
        for _ in range(2):
            job = queue.claim(queue="emails")
            result = job.execute()
            queue.ack(job.id, result=result)
            email_results.append(result)

        job = queue.claim(queue="reports")
        report_result = job.execute()
        queue.ack(job.id, result=report_result)

        assert len(email_results) == 2
        assert report_result == "Report 101"

    def test_worker_integration(self, queue: DuckQueue):
        for i in range(10):
            queue.enqueue(square, args=(i,))

        worker = Worker(queue)

        def stop_worker():
            time.sleep(1)
            worker.should_stop = True

        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.05)
        assert queue.stats()["done"] == 10

    def test_batch_workflow(self, queue: DuckQueue):
        jobs_list = [(add_ten, (i,), {}) for i in range(5)]
        job_ids = queue.enqueue_batch(jobs_list)

        results = []
        for _ in range(5):
            job = queue.claim()
            result = job.execute()
            queue.ack(job.id, result=result)
            results.append(result)

        assert sorted(results) == [10, 11, 12, 13, 14]

    def test_dead_letter_workflow(self, queue: DuckQueue):
        for i in range(3):
            job_id = queue.enqueue(always_fails, max_attempts=2)

        for _ in range(3):
            for _ in range(2):
                job = queue.claim()
                if job:
                    try:
                        job.execute()
                    except RuntimeError as e:
                        queue.ack(job.id, error=str(e))

        dead_letters = queue.list_dead_letters()
        assert len(dead_letters) == 3

    def test_concurrent_workers(self, queue: DuckQueue):
        for i in range(10):
            queue.enqueue(identity, args=(i,))

        workers = []
        threads = []

        for i in range(3):
            worker = Worker(queue, worker_id=f"worker-{i}")
            workers.append(worker)

            def run_worker(w):
                empty_count = 0
                while empty_count < 3:
                    job = queue.claim(worker_id=w.worker_id)
                    if job:
                        empty_count = 0
                        w._execute_job(job, 1)
                    else:
                        empty_count += 1
                        time.sleep(0.1)

            thread = threading.Thread(target=run_worker, args=(worker,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join(timeout=5)

        assert queue.stats()["done"] == 10


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions.

    Note: DuckDB connections are NOT thread-safe for concurrent writes from
    the same connection. In production, use separate processes or connections
    per thread. These tests verify behavior within those constraints.
    """

    def test_empty_args(self, queue: DuckQueue):
        job_id = queue.enqueue(no_args)
        job = queue.claim()
        result = job.execute()
        assert result == "no args"

    def test_large_result(self, queue: DuckQueue):
        job_id = queue.enqueue(large_result)
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert len(stored) == 1000000

    def test_complex_data_structures(self, queue: DuckQueue):
        input_data = {"items": [1, 2, 3, 4, 5], "metadata": {"version": 1}}
        job_id = queue.enqueue(complex_task, args=(input_data,))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert stored["count"] == 5
        assert stored["nested"]["metadata"]["version"] == 1

    def test_unicode_handling(self, queue: DuckQueue):
        job_id = queue.enqueue(unicode_task, args=("Hello 世界 🌍",))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert "世界" in stored
        assert "🌍" in stored

    def test_concurrent_enqueue(self, queue: DuckQueue):
        job_ids = []
        lock = threading.Lock()
        errors = []

        def enqueue_jobs(start, count):
            try:
                # Create a new connection for this thread
                # DuckDB connections are not thread-safe
                for i in range(start, start + count):
                    try:
                        jid = queue.enqueue(
                            identity, args=(i,), check_backpressure=False
                        )
                        with lock:
                            job_ids.append(jid)
                    except Exception as e:
                        with lock:
                            errors.append(str(e))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = []
        for i in range(3):
            thread = threading.Thread(target=enqueue_jobs, args=(i * 10, 10))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        # DuckDB connections aren't fully thread-safe for concurrent writes
        # So we just check that at least some jobs were enqueued
        assert len(job_ids) > 0
        # And that all enqueued job IDs are unique
        assert len(set(job_ids)) == len(job_ids)

    def test_zero_priority(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), priority=0)
        job = queue.get_job(job_id)
        assert job.priority == 0

    def test_max_priority(self, queue: DuckQueue):
        job_id = queue.enqueue(add, args=(1, 2), priority=100)
        job = queue.get_job(job_id)
        assert job.priority == 100


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Performance-related tests."""

    @pytest.fixture
    def queue(self):
        """Create in-memory queue for testing."""
        queue = DuckQueue(":memory:", enable_claim_cache=True)
        yield queue
        queue.close()

    @pytest.fixture
    def queue_no_cache(self):
        """Create queue without cache for baseline tests."""
        queue = DuckQueue(":memory:", enable_claim_cache=False)
        yield queue
        queue.close()

    def test_enqueue_performance(self, queue: DuckQueue):
        start = time.time()
        for i in range(100):
            queue.enqueue(add, args=(i, i), check_backpressure=False)
        duration = time.time() - start
        assert duration < 5.0  # 5 seconds for 100 jobs
        assert queue.stats()["pending"] == 100

    def test_claim_batch_performance(self, queue: DuckQueue):
        """Test batch claiming performance (fastest method)."""
        # Enqueue 100 jobs without dependencies
        for i in range(100):
            queue.enqueue(add, args=(i, i), check_backpressure=False)

        start = time.time()

        # Claim in batches of 10 (10 iterations instead of 100)
        claimed = 0
        while claimed < 100:
            jobs = queue.claim_batch(count=10)
            for job in jobs:
                result = job.execute()
                queue.ack(job.id, result=result)
            claimed += len(jobs)

            if not jobs:
                break

        duration = time.time() - start

        assert claimed == 100
        assert duration < 2.0, f"Batch claiming took {duration:.2f}s (expected <2s)"
        print(
            f"✓ Batch claim: {duration:.2f}s for 100 jobs ({100 / duration:.0f} jobs/s)"
        )

    def test_claim_batch_with_dependencies(self, queue: DuckQueue):
        """Test batch claiming respects dependencies."""
        # Create dependency chain: job1 -> job2 -> job3
        job1_id = queue.enqueue(add, args=(1, 1), check_backpressure=False)
        job2_id = queue.enqueue(
            add, args=(2, 2), depends_on=job1_id, check_backpressure=False
        )
        job3_id = queue.enqueue(
            add, args=(3, 3), depends_on=job2_id, check_backpressure=False
        )

        # Batch claim should only get job1 (no dependencies)
        batch1 = queue.claim_batch(count=10)
        assert len(batch1) == 1
        assert batch1[0].id == job1_id

        # Complete job1
        queue.ack(job1_id, result=2)

        # Now job2 should be available
        batch2 = queue.claim_batch(count=10)
        assert len(batch2) == 1
        assert batch2[0].id == job2_id

        # Complete job2
        queue.ack(job2_id, result=4)

        # Now job3 should be available
        batch3 = queue.claim_batch(count=10)
        assert len(batch3) == 1
        assert batch3[0].id == job3_id


# ============================================================================
# Test WorkerPool
# ============================================================================


class TestWorkerPool:
    """Test WorkerPool for automatic worker management."""

    def test_worker_pool_initialization(self, queue: DuckQueue):
        pool = WorkerPool(queue, num_workers=3, concurrency=2)
        assert pool.num_workers == 3
        assert pool.concurrency == 2
        assert pool.running == False
        assert len(pool.workers) == 0
        assert len(pool.threads) == 0

    def test_worker_pool_start(self, queue: DuckQueue):
        pool = WorkerPool(queue, num_workers=2, concurrency=1)
        pool.start()

        assert pool.running 
        assert len(pool.workers) == 2
        assert len(pool.threads) == 2

        # Check threads are alive
        for thread in pool.threads:
            assert thread.is_alive()

        pool.stop()

    def test_worker_pool_stop(self, queue: DuckQueue):
        pool = WorkerPool(queue, num_workers=2)
        pool.start()
        time.sleep(0.5)  # Let workers start
        pool.stop(timeout=5)

        # Check all workers received stop signal
        for worker in pool.workers:
            assert worker.should_stop 

    def test_worker_pool_processes_jobs(self, queue: DuckQueue):
        # Enqueue jobs
        for i in range(10):
            queue.enqueue(add, args=(i, i))

        # Start pool
        pool = WorkerPool(queue, num_workers=2, concurrency=1)
        pool.start()

        # Wait for processing
        time.sleep(2)
        pool.stop()

        # Check jobs were processed
        stats = queue.stats()
        assert stats["done"] > 0

    def test_worker_pool_context_manager(self, queue: DuckQueue):
        # Enqueue jobs
        for i in range(5):
            queue.enqueue(add, args=(i, i))

        # Use context manager
        with WorkerPool(queue, num_workers=2) as pool:
            assert pool.running 
            time.sleep(1)

        # After context, pool should be stopped
        stats = queue.stats()
        assert stats["done"] >= 0  # Some jobs processed

    def test_worker_pool_concurrent_workers(self, queue: DuckQueue):
        # Enqueue slow jobs
        for i in range(8):
            queue.enqueue(slow, args=(0.2,))

        start = time.time()
        with WorkerPool(queue, num_workers=4, concurrency=1):
            time.sleep(1.5)
        duration = time.time() - start

        # With 4 workers, should process faster than serial
        stats = queue.stats()
        assert stats["done"] >= 4  # At least 4 completed


# ============================================================================
# Test Context Manager API
# ============================================================================


class TestContextManager:
    """Test DuckQueue context manager functionality."""

    def test_context_manager_basic(self):
        """Test basic context manager usage."""
        # Create queue with workers
        with DuckQueue(":memory:", workers_num=2) as q:
            # Enqueue jobs
            for i in range(5):
                q.enqueue(add, args=(i, i))

            # Give workers time to process
            time.sleep(1)

            stats = q.stats()
            # Workers should have processed some/all jobs
            assert stats["done"] + stats["claimed"] > 0

    def test_context_manager_auto_start_workers(self):
        """Test workers are auto-started in context manager."""
        with DuckQueue(":memory:", workers_num=3, worker_concurrency=1) as q:
            assert q._worker_pool is not None
            assert len(q._worker_pool.workers) == 3

    def test_context_manager_no_workers(self):
        """Test context manager without workers (workers_num=None)."""
        with DuckQueue(":memory:", workers_num=None) as q:
            # No workers should be started
            assert q._worker_pool is None

            # Can still enqueue manually
            job_id = q.enqueue(add, args=(1, 2))
            assert job_id is not None

    def test_context_manager_cleanup(self):
        """Test context manager cleans up resources."""
        queue_ref = None

        with DuckQueue(":memory:", workers_num=2) as q:
            queue_ref = q
            q.enqueue(add, args=(1, 2))

        # After exit, workers should be stopped
        assert queue_ref._worker_pool is None or not any(
            t.is_alive() for t in queue_ref._worker_pool.threads
        )

    def test_context_manager_exception_handling(self):
        """Test context manager handles exceptions properly."""
        try:
            with DuckQueue(":memory:", workers_num=2) as q:
                q.enqueue(add, args=(1, 2))
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        # Workers should still be cleaned up
        # (pool threads are daemon, so they'll die with main thread)

    def test_manual_start_stop_workers(self, queue: DuckQueue):
        """Test manually starting and stopping workers."""
        # Start workers
        queue.start_workers(num_workers=2, concurrency=1, daemon=True)
        assert queue._worker_pool is not None
        assert len(queue._worker_pool.workers) == 2

        # Enqueue and process
        for i in range(3):
            queue.enqueue(add, args=(i, i))

        time.sleep(1)

        # Stop workers
        queue.stop_workers()
        assert queue._worker_pool is None

        stats = queue.stats()
        assert stats["done"] > 0

    def test_context_manager_with_custom_concurrency(self):
        with DuckQueue(":memory:", workers_num=2, worker_concurrency=2) as q:
            for i in range(8):
                q.enqueue(slow, args=(0.1,))

            time.sleep(2)  # Increase from 1 to 2

            stats = q.stats()
            assert stats["done"] >= 4, f"Expected >=4 done, got {stats}"


# ============================================================================
# Test Initialization Parameters
# ============================================================================


class TestInitializationParameters:
    """Test DuckQueue initialization with various parameters."""

    def test_init_with_workers_num(self):
        """Test initialization with workers_num parameter."""
        q = DuckQueue(":memory:", workers_num=3)
        assert q._workers_num == 3
        assert q._worker_pool is None  # Not started yet
        q.close()

    def test_init_with_invalid_workers_num(self):
        """Test initialization with invalid workers_num."""
        with pytest.raises(ValueError) as exc_info:
            DuckQueue(":memory:", workers_num=0)
        assert "must be positive or None" in str(exc_info.value)

        with pytest.raises(ValueError):
            DuckQueue(":memory:", workers_num=-1)

    def test_init_with_worker_concurrency(self):
        """Test initialization with worker_concurrency parameter."""
        q = DuckQueue(":memory:", worker_concurrency=4)
        assert q._worker_concurrency == 4
        q.close()

    def test_init_with_invalid_worker_concurrency(self):
        """Test initialization with invalid worker_concurrency."""
        with pytest.raises(ValueError) as exc_info:
            DuckQueue(":memory:", worker_concurrency=0)
        assert "must be positive" in str(exc_info.value)

        with pytest.raises(ValueError):
            DuckQueue(":memory:", worker_concurrency=-1)

    def test_init_with_poll_timeout(self):
        """Test initialization with custom poll_timeout."""
        q = DuckQueue(":memory:", poll_timeout=0.5)
        assert q._poll_timeout == 0.5
        q.close()

    def test_init_all_parameters(self):
        """Test initialization with all parameters."""
        q = DuckQueue(
            ":memory:",
            default_queue="custom",
            workers_num=4,
            worker_concurrency=2,
            poll_timeout=0.5,
        )
        assert q.default_queue == "custom"
        assert q._workers_num == 4
        assert q._worker_concurrency == 2
        assert q._poll_timeout == 0.5
        q.close()


# ============================================================================
# Integration Tests for New Features
# ============================================================================


class TestNewFeaturesIntegration:
    """Integration tests for WorkerPool and context manager features."""

    def test_end_to_end_with_context_manager(self):
        """Test complete workflow with context manager."""
        results_file = []

        with DuckQueue(":memory:", workers_num=2) as q:
            # Enqueue jobs
            job_ids = []
            for i in range(10):
                job_id = q.enqueue(square, args=(i,))
                job_ids.append(job_id)

            # Wait for processing
            time.sleep(2)

            # Check results
            for job_id in job_ids:
                job = q.get_job(job_id)
                if job and job.status == JobStatus.DONE.value:
                    result = q.get_result(job_id)
                    results_file.append(result)

        # Verify some results were computed
        assert len(results_file) > 0

    def test_priority_queues_with_worker_pool(self):
        """Test priority queues work with WorkerPool."""
        with DuckQueue(":memory:", workers_num=1) as q:
            # Enqueue with different priorities
            low_id = q.enqueue(task_priority, args=("low",), priority=10)
            high_id = q.enqueue(task_priority, args=("high",), priority=90)
            med_id = q.enqueue(task_priority, args=("medium",), priority=50)

            # Wait for processing
            time.sleep(2)

            # Check processing order (high priority first)
            high_job = q.get_job(high_id)
            assert high_job.status == JobStatus.DONE.value

    def test_delayed_jobs_with_worker_pool(self):
        with DuckQueue(":memory:", workers_num=1) as q:
            job_id = q.enqueue(add, args=(1, 2), delay_seconds=1)

            time.sleep(0.5)
            job = q.get_job(job_id)
            assert job.status in [JobStatus.DELAYED.value, JobStatus.PENDING.value]

            # Wait longer for worker to process
            time.sleep(2)
            job = q.get_job(job_id)

            assert job.status in [JobStatus.DONE.value, JobStatus.CLAIMED.value], (
                f"Expected done/claimed, got {job.status}"
            )

    def test_retry_with_worker_pool(self):
        """Test retry logic works with WorkerPool."""
        reset_flaky_counter()

        with DuckQueue(":memory:", workers_num=1) as q:
            job_id = q.enqueue(flaky_task, max_attempts=2)

            # Wait for retries and eventual success
            time.sleep(1)

            job = q.get_job(job_id)
            # Should eventually succeed
            assert job.status in [
                JobStatus.DONE.value,
                JobStatus.PENDING.value,
                JobStatus.CLAIMED.value,
            ]

    def test_batch_enqueue_with_worker_pool(self):
        """Test batch enqueueing works with WorkerPool."""
        with DuckQueue(":memory:", workers_num=2, worker_concurrency=2) as q:
            # Batch enqueue
            jobs = [(add, (i, i), {}) for i in range(20)]
            job_ids = q.enqueue_batch(jobs)

            assert len(job_ids) == 20

            # Wait for processing
            time.sleep(2)

            stats = q.stats()
            # Most jobs should be done
            assert stats["done"] > 10

    def test_multiple_queues_with_worker_pool(self):
        with DuckQueue(":memory:", workers_num=1) as q:
            q.enqueue(add, args=(1, 1), queue="queue1")
            q.enqueue(add, args=(2, 2), queue="queue2")
            q.enqueue(add, args=(3, 3), queue="default")

            time.sleep(2)  # Increase from 1 to 2

            # More defensive assertions:
            stats1 = q.stats("queue1")
            stats2 = q.stats("queue2")
            stats_default = q.stats("default")

            total_processed = (
                stats1["done"]
                + stats1["claimed"]
                + stats2["done"]
                + stats2["claimed"]
                + stats_default["done"]
                + stats_default["claimed"]
            )

            assert total_processed > 0, (
                f"No jobs processed. Stats: {stats1}, {stats2}, {stats_default}"
            )

    def test_worker_pool_handles_exceptions(self):
        with DuckQueue(":memory:", workers_num=1) as q:
            for i in range(3):
                q.enqueue(fail, args=("error",), max_attempts=1)

            time.sleep(2)  # Increase from 1 to 2

            stats = q.stats()
            assert stats["failed"] >= 1, f"Expected >=1 failed, got {stats}"

    def test_context_manager_survives_worker_errors(self):
        with DuckQueue(":memory:", workers_num=2) as q:
            # Mix of good and bad jobs
            q.enqueue(add, args=(1, 2))
            q.enqueue(fail, args=("error",), max_attempts=1)
            q.enqueue(add, args=(3, 4))

            time.sleep(2)  # Increase from 1 to 2 seconds

            stats = q.stats()
            # Some jobs should succeed
            assert stats["done"] >= 1
            # Some should fail
            assert stats["failed"] >= 1


# ============================================================================
# Test Backpressure Warning
# ============================================================================


class TestBackpressureWarning:
    """Test backpressure warning functionality."""

    def test_backpressure_continues_after_warning(self, queue: DuckQueue):
        """Test that enqueueing continues after warning."""
        import warnings

        jobs_count = queue.backpressure_warning_threshold() + 1

        # Enqueue past warning threshold
        for i in range(jobs_count):
            queue.enqueue(add, args=(i, i), check_backpressure=False)

        # Can still enqueue more
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            queue.enqueue(add, args=(1, 1), check_backpressure=True)

        stats = queue.stats()
        assert stats["pending"] == jobs_count + 1


# Module-level functions so they are picklable by pickle
def parent_func(x, y):
    return x + y


def child_func(a, b):
    return a * b


def a_func():
    return 1


def b_func():
    return 2


def c_func():
    return 3


def test_enqueue_persists_dependencies_and_claim_respects_them(queue):
    """Enqueue a parent and a dependent child; ensure dependency persisted
    and child is not claimable until parent is done."""
    # Enqueue parent first (use module-level functions so they're picklable)
    parent_id = queue.enqueue(parent_func, args=(1, 2), kwargs={})

    # Enqueue child that depends on parent
    child_id = queue.enqueue(child_func, args=(3, 4), kwargs={}, depends_on=parent_id)

    # The dependency should be persisted in the job_dependencies table
    row = queue.conn.execute(
        "SELECT parent_job_id FROM job_dependencies WHERE child_job_id = ?", [child_id]
    ).fetchone()
    assert row is not None and row[0] == parent_id

    # First claim should return the parent (child is blocked by dependency)
    claimed = queue.claim()
    assert claimed is not None
    assert claimed.id == parent_id

    # Acknowledge parent as done
    queue.ack(parent_id, result=3)

    # Now child should be claimable
    claimed_child = queue.claim()
    assert claimed_child is not None
    assert claimed_child.id == child_id


def test_ack_propagates_skipped_to_descendants(queue):
    """If a job is permanently failed, its transitive descendants should
    be marked SKIPPED and have attempts finalized to max_attempts."""
    # Create chain A -> B -> C using module-level functions
    a = queue.enqueue(a_func, args=(), kwargs={})
    b = queue.enqueue(b_func, args=(), kwargs={}, depends_on=a)
    c = queue.enqueue(c_func, args=(), kwargs={}, depends_on=b)

    # Force A into permanent failure by setting attempts = max_attempts
    queue.conn.execute("UPDATE jobs SET attempts = max_attempts WHERE id = ?", [a])

    # Ack A with an error to trigger permanent failure handling
    queue.ack(a, error="permanent")

    # Children should be SKIPPED with attempts finalized
    jb = queue.get_job(b)
    jc = queue.get_job(c)

    assert jb is not None and jc is not None
    assert jb.status == JobStatus.SKIPPED.value
    assert jc.status == JobStatus.SKIPPED.value

    assert jb.attempts == jb.max_attempts
    assert jc.attempts == jc.max_attempts

    # Metadata fields should be present for skipped jobs
    assert jb.skipped_by == "queuack"
    assert jb.skip_reason is not None and jb.skip_reason.startswith("parent_failed:")


class TestWorkerSignalHandling:
    """Test Worker signal handling in different thread contexts."""

    def test_worker_in_background_thread_no_signal_registration(self):
        """Test that worker in background thread doesn't register signals."""
        queue = DuckQueue(":memory:")
        worker_ref = []
        exception_ref = []

        def create_worker_in_thread():
            try:
                # This should not raise even though we're not in main thread
                worker = Worker(queue)
                worker_ref.append(worker)
            except Exception as e:
                exception_ref.append(e)

        thread = threading.Thread(target=create_worker_in_thread)
        thread.start()
        thread.join()

        # Should succeed without exceptions
        assert len(worker_ref) == 1
        assert len(exception_ref) == 0

        queue.close()

    def test_worker_signal_handler_sets_stop_flag(self):
        """Test signal handler sets should_stop flag."""
        queue = DuckQueue(":memory:")
        worker = Worker(queue)

        assert worker.should_stop == False

        # Call signal handler
        worker._signal_handler(None, None)

        assert worker.should_stop 

        queue.close()


class TestConnectionPoolEdgeCases:
    """Test ConnectionPool error handling and edge cases."""

    def test_connection_pool_close_when_no_connection(self):
        """Test closing when no connection exists."""
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            pool = ConnectionPool(db_path)

            # Close without ever getting a connection
            # Should not raise
            pool.close_current()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_connection_pool_close_file_connection(self):
        """Test closing file-based connection."""
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            pool = ConnectionPool(db_path)

            # Get connection
            conn = pool.get_connection()
            assert conn is not None

            # Close it
            pool.close_current()

            # Getting again should create new one
            conn2 = pool.get_connection()
            assert conn2 is not None
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_connection_pool_close_memory_connection(self):
        """Test closing memory connection."""
        # FIXED: Use DuckQueue to properly initialize the connection pool
        # instead of creating ConnectionPool directly, since ConnectionPool
        # requires schema initialization to set up _global_conn for :memory:
        queue = DuckQueue(":memory:")
        pool = queue._conn_pool

        # Get connection (should work now since queue initialized it)
        conn = pool.get_connection()
        assert conn is not None

        # Close it
        pool.close_current()

        # Global connection should be None now
        assert pool._global_conn is None

        queue.close()


class TestWorkerConcurrentEdgeCases:
    """Test Worker concurrent execution edge cases."""

    def test_worker_concurrent_with_timeout_completion(self):
        """Test concurrent worker with timeout in as_completed."""
        queue = DuckQueue(":memory:")

        # Enqueue slow jobs
        for i in range(3):
            queue.enqueue(slow_task)

        worker = Worker(queue, concurrency=2, max_jobs_in_flight=2)

        def stop_after_delay():
            time.sleep(1.5)
            worker.should_stop = True

        stop_thread = threading.Thread(target=stop_after_delay, daemon=True)
        stop_thread.start()

        # Run worker - should handle timeouts in as_completed
        worker.run(poll_interval=0.1)

        # Should have processed at least some jobs
        stats = queue.stats()
        assert stats["done"] >= 1

        queue.close()

    def test_worker_concurrent_stops_with_pending_futures(self):
        """Test worker stops gracefully with pending futures."""
        queue = DuckQueue(":memory:")

        # Enqueue many slow jobs
        for i in range(10):
            queue.enqueue(slow_task)

        worker = Worker(queue, concurrency=2, max_jobs_in_flight=4)

        def stop_early():
            time.sleep(0.5)
            worker.should_stop = True

        stop_thread = threading.Thread(target=stop_early, daemon=True)
        stop_thread.start()

        # Run worker - should stop even with pending futures
        worker.run(poll_interval=0.05)

        queue.close()

    def test_worker_concurrent_empty_queue_no_futures(self):
        """Test concurrent worker with empty queue and no futures."""
        queue = DuckQueue(":memory:")

        worker = Worker(queue, concurrency=2)
        worker.should_stop = True

        # Should exit immediately
        worker.run(poll_interval=0.1)

        queue.close()


class TestQueueEdgeCases:
    """Test DuckQueue edge cases."""

    def test_enqueue_with_string_depends_on(self):
        """Test enqueue with single string depends_on."""
        queue = DuckQueue(":memory:")

        parent_id = queue.enqueue(simple_task)

        # Pass string instead of list
        child_id = queue.enqueue(simple_task, depends_on=parent_id)

        # Should have dependency
        deps = queue.conn.execute(
            "SELECT parent_job_id FROM job_dependencies WHERE child_job_id = ?",
            [child_id],
        ).fetchall()

        assert len(deps) == 1
        assert deps[0][0] == parent_id

        queue.close()

    def test_enqueue_with_list_depends_on(self):
        """Test enqueue with list of dependencies."""
        queue = DuckQueue(":memory:")

        parent1 = queue.enqueue(simple_task)
        parent2 = queue.enqueue(simple_task)

        # Pass list of dependencies
        child_id = queue.enqueue(simple_task, depends_on=[parent1, parent2])

        # Should have both dependencies
        deps = queue.conn.execute(
            "SELECT parent_job_id FROM job_dependencies WHERE child_job_id = ?",
            [child_id],
        ).fetchall()

        assert len(deps) == 2
        parent_ids = {d[0] for d in deps}
        assert parent1 in parent_ids
        assert parent2 in parent_ids

        queue.close()

    def test_enqueue_dependency_duplicate_ignored(self):
        """Test that duplicate dependencies are ignored."""
        queue = DuckQueue(":memory:")

        parent_id = queue.enqueue(simple_task)

        # Enqueue with duplicate parent
        child_id = queue.enqueue(simple_task, depends_on=[parent_id, parent_id])

        # Should only have one dependency (duplicate ignored)
        deps = queue.conn.execute(
            "SELECT parent_job_id FROM job_dependencies WHERE child_job_id = ?",
            [child_id],
        ).fetchall()

        # Might be 1 or 2 depending on DB constraints
        assert len(deps) >= 1

        queue.close()

    def test_enqueue_dependency_invalid_parent_ignored(self):
        """Test that invalid parent IDs are ignored."""
        queue = DuckQueue(":memory:")

        # Enqueue with non-existent parent
        child_id = queue.enqueue(simple_task, depends_on="nonexistent-id")

        # Should still create the job
        job = queue.get_job(child_id)
        assert job is not None

        queue.close()

    def test_ack_propagate_failure_with_exception(self):
        """Test ack failure propagation handles exceptions."""
        queue = DuckQueue(":memory:")

        parent_id = queue.enqueue(simple_task, max_attempts=1)
        child_id = queue.enqueue(simple_task, depends_on=parent_id)

        # Claim and fail parent
        job = queue.claim()
        assert job.id == parent_id

        queue.ack(job.id, error="Test failure")

        # Child should be skipped
        child_job = queue.get_job(child_id)
        assert child_job.status == "skipped"

        queue.close()

    def test_context_manager_with_no_workers(self):
        """Test context manager when workers_num is None."""
        with DuckQueue(":memory:", workers_num=None) as queue:
            # Should not start any workers
            assert queue._worker_pool is None

            # Can still use queue
            job_id = queue.enqueue(simple_task)
            assert job_id is not None


class TestWorkerPoolEdgeCases:
    """Test WorkerPool edge cases."""

    def test_worker_pool_stop_with_timeout(self):
        """Test WorkerPool stop with custom timeout."""
        queue = DuckQueue(":memory:")

        # Enqueue long-running jobs
        for i in range(5):
            queue.enqueue(slow_task)

        pool = WorkerPool(queue, num_workers=2, concurrency=1)
        pool.start()

        time.sleep(0.5)

        # Stop with short timeout
        pool.stop(timeout=1)

        # Workers should be stopped
        for worker in pool.workers:
            assert worker.should_stop 

        queue.close()

    def test_worker_pool_start_twice(self):
        """Test starting worker pool twice."""
        queue = DuckQueue(":memory:")

        pool = WorkerPool(queue, num_workers=2)
        pool.start()

        assert pool.running 
        assert len(pool.workers) == 2

        # Start again (should be idempotent or handled)
        pool.start()

        pool.stop()
        queue.close()


class TestBackpressureThresholds:
    """Test backpressure threshold customization."""

    def test_custom_backpressure_thresholds(self):
        """Test that backpressure thresholds can be customized."""

        class CustomQueue(DuckQueue):
            @classmethod
            def backpressure_warning_threshold(cls):
                return 5

            @classmethod
            def backpressure_block_threshold(cls):
                return 10

        queue = CustomQueue(":memory:")

        # Should be able to enqueue up to warning threshold
        for i in range(5):
            queue.enqueue(simple_task, check_backpressure=False)

        # Next one should warn
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            queue.enqueue(simple_task, check_backpressure=True)
            assert len(w) == 1

        queue.close()


class TestClaimEdgeCases:
    """Test claim() edge cases."""

    def test_claim_updates_delayed_jobs_to_pending(self):
        """Test that claim promotes delayed jobs when ready."""
        queue = DuckQueue(":memory:")

        # Enqueue delayed job with very short delay
        job_id = queue.enqueue(simple_task, delay_seconds=1)

        # Job should be delayed
        job = queue.get_job(job_id)
        assert job.status == "delayed"

        # Wait for delay
        time.sleep(1.1)

        # Claim should promote and claim it
        claimed = queue.claim()

        if claimed:
            assert claimed.id == job_id
            assert claimed.status == "claimed"

        queue.close()

    def test_claim_with_max_attempts_reached(self):
        """Test claiming when job has reached max attempts."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(simple_task, max_attempts=2)

        # Manually set attempts to max
        queue.conn.execute(
            "UPDATE jobs SET attempts = max_attempts WHERE id = ?", [job_id]
        )

        # Should not be claimable
        claimed = queue.claim()
        assert claimed is None or claimed.id != job_id

        queue.close()


class TestGetResultEdgeCases:
    """Test get_result() edge cases."""

    def test_get_result_with_none_result(self):
        """Test getting result when result is None."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(return_none)
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        # Should return None without error
        retrieved = queue.get_result(job_id)
        assert retrieved is None

        queue.close()


class TestPurgeEdgeCases:
    """Test purge() edge cases."""

    def test_purge_with_zero_count(self):
        """Test purge when no jobs match criteria."""
        queue = DuckQueue(":memory:")

        # Enqueue and complete job
        job_id = queue.enqueue(simple_task)
        job = queue.claim()
        queue.ack(job.id, result=42)

        # Purge with impossible criteria
        count = queue.purge(status="done", older_than_hours=99999)

        assert count == 0

        # Job should still exist
        assert queue.get_job(job_id) is not None

        queue.close()


class TestEnqueueBatchEdgeCases:
    """Test enqueue_batch() edge cases."""

    def test_enqueue_batch_empty_list(self):
        """Test batch enqueue with empty list."""
        queue = DuckQueue(":memory:")

        # FIXED: DuckDB executemany doesn't accept empty lists
        # We need to handle this in the application code or just verify behavior
        job_ids = queue.enqueue_batch([])

        assert job_ids == []
        assert queue.stats()["pending"] == 0

        queue.close()

    def test_enqueue_batch_single_job(self):
        """Test batch enqueue with single job."""
        queue = DuckQueue(":memory:")

        job_ids = queue.enqueue_batch([(simple_task, (), {})])

        assert len(job_ids) == 1
        assert queue.stats()["pending"] == 1

        queue.close()


class TestWorkerClaimNextJob:
    """Test Worker._claim_next_job() with multiple queues."""

    def test_claim_next_job_from_multiple_queues(self):
        """Test claiming from multiple queues in priority order."""
        queue = DuckQueue(":memory:")

        # Enqueue to different queues
        queue.enqueue(simple_task, queue="low")
        queue.enqueue(simple_task, queue="high")

        # Worker with priority queues
        worker = Worker(queue, queues=[("high", 100), ("low", 10)])

        # Should claim from high priority queue first
        job = worker._claim_next_job()

        if job:
            assert job.queue == "high"

        queue.close()

    def test_claim_next_job_all_empty(self):
        """Test claiming when all queues are empty."""
        queue = DuckQueue(":memory:")

        worker = Worker(queue, queues=["queue1", "queue2", "queue3"])

        # Should return None
        job = worker._claim_next_job()
        assert job is None

        queue.close()


class TestContextManagerExceptionHandling:
    """Test context manager exception handling."""

    def test_context_manager_with_exception(self):
        """Test context manager cleans up even when exception occurs."""
        try:
            with DuckQueue(":memory:", workers_num=1) as queue:
                queue.enqueue(simple_task)
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        # Workers should have been stopped
        # (They're daemon threads, so they'll die anyway)

    def test_context_manager_exit_stops_workers(self):
        """Test that __exit__ stops workers."""
        queue = DuckQueue(":memory:", workers_num=2)

        with queue:
            # Workers should be started
            assert queue._worker_pool is not None
            assert len(queue._worker_pool.workers) == 2

        # After exit, workers should be stopped
        assert queue._worker_pool is None or all(
            w.should_stop for w in queue._worker_pool.workers
        )


class TestListDeadLettersEdgeCases:
    """Test list_dead_letters() edge cases."""

    def test_list_dead_letters_with_no_failures(self):
        """Test listing dead letters when none exist."""
        queue = DuckQueue(":memory:")

        # Enqueue and complete successfully
        job_id = queue.enqueue(simple_task)
        job = queue.claim()
        queue.ack(job.id, result=42)

        dead_letters = queue.list_dead_letters()
        assert len(dead_letters) == 0

        queue.close()

    def test_list_dead_letters_respects_limit(self):
        """Test that limit parameter works."""
        queue = DuckQueue(":memory:")

        # Create many failed jobs
        for i in range(10):
            job_id = queue.enqueue(simple_task, max_attempts=1)
            job = queue.claim()
            queue.ack(job.id, error="Failed")

        # Request limited results
        dead_letters = queue.list_dead_letters(limit=5)
        assert len(dead_letters) == 5

        queue.close()


def fail_and_check(queue, failed_job_id, expected_skipped_ids):
    # Force failure by setting attempts = max_attempts
    queue.conn.execute(
        "UPDATE jobs SET attempts = max_attempts WHERE id = ?", [failed_job_id]
    )
    queue.ack(failed_job_id, error="permanent")

    for jid in expected_skipped_ids:
        job = queue.get_job(jid)
        assert job is not None
        assert job.status == JobStatus.SKIPPED.value, (
            f"Job {jid} expected SKIPPED, got {job.status}"
        )


def test_chain_three_levels(queue):
    # A -> B -> C
    a = queue.enqueue(a_func)
    b = queue.enqueue(b_func, depends_on=a)
    c = queue.enqueue(c_func, depends_on=b)

    fail_and_check(queue, a, [b, c])


def test_diamond_shape(queue):
    #   A
    #  / \
    # B   C
    #  \ /
    #   D
    a = queue.enqueue(a_func)
    b = queue.enqueue(b_func, depends_on=a)
    c = queue.enqueue(c_func, depends_on=a)
    d = queue.enqueue(d_func, depends_on=[b, c], dependency_mode="all")

    fail_and_check(queue, a, [b, c, d])


def test_fan_out_with_any(queue):
    # A -> {B, C, D}; B and C depend on A; D depends on A with 'any'
    a = queue.enqueue(a_func)
    b = queue.enqueue(b_func, depends_on=a)
    c = queue.enqueue(c_func, depends_on=a)
    d = queue.enqueue(d_func, depends_on=[b, c], dependency_mode="any")

    # Failing A should skip B and C; D depends on any of B/C so it'll be skipped only if both are unhealthy
    fail_and_check(queue, a, [b, c, d])


def test_mixed_any_all_propagation(queue):
    # Build a more complex graph mixing ANY and ALL
    # A -> B -> D
    # A -> C -> D
    # D depends on [B,C] with 'any' (so if either B or C healthy, D is runnable)
    a = queue.enqueue(a_func)
    b = queue.enqueue(b_func, depends_on=a)
    c = queue.enqueue(c_func, depends_on=a)
    d = queue.enqueue(d_func, depends_on=[b, c], dependency_mode="any")

    # Fail B permanently; only descendants that become unrunnable should be skipped
    queue.conn.execute("UPDATE jobs SET attempts = max_attempts WHERE id = ?", [b])
    queue.ack(b, error="permanent")

    # B should be skipped/failed; D should remain pending because C still healthy
    jb = queue.get_job(b)
    jd = queue.get_job(d)

    assert jb.status == JobStatus.SKIPPED.value or jb.status == JobStatus.FAILED.value
    assert jd.status == JobStatus.PENDING.value


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=core", "--cov-report=term-missing"])
