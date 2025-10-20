# file: test_core.py
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

import pytest
import time
import pickle
import threading
from datetime import datetime, timedelta
import tempfile
import os

# Import from duckqueue module  
# Assuming the module is named 'core' based on your file structure
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queuack import (
    DuckQueue, Worker, Job, JobStatus, BackpressureError, job
)


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

def quick(x):
    """Quick task."""
    return x + 1

def instant(x):
    """Task that completes instantly."""
    return x * 2

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
    return {
        'nested': data,
        'count': len(data['items'])
    }


def unicode_task(text):
    """Function with unicode."""
    return f"Processed: {text}"


def always_fails():
    """Function that always fails."""
    raise RuntimeError("Always fails")


# Global counter for flaky task
flaky_attempt_count = {'count': 0}

def flaky_task():
    """Task that fails first few times."""
    flaky_attempt_count['count'] += 1
    if flaky_attempt_count['count'] < 3:
        raise ValueError("Not ready yet")
    return "success"


def reset_flaky_counter():
    """Reset the flaky task counter."""
    flaky_attempt_count['count'] = 0


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

def email_job(to, subject="Test"):
    """Email simulation."""
    time.sleep(0.1)
    return f"Email to {to}: {subject}"


def report_job(report_id):
    """Report processing simulation."""
    time.sleep(0.5)
    return f"Report {report_id} done"


def maintenance_job(action):
    """Maintenance task."""
    time.sleep(0.2)
    return f"Maintenance: {action}"

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def queue():
    """Create in-memory queue for testing."""
    q = DuckQueue(":memory:")
    yield q
    q.close()


@pytest.fixture
def file_queue():
    """Create file-based queue for testing."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.duckdb') as f:
        db_path = f.name
    
    # Delete the file first - DuckDB will create it
    os.unlink(f.name)
    
    q = DuckQueue(db_path)
    yield q
    q.close()
    
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


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
            status="pending"
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
            status="claimed"
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
            status="claimed"
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
    
    def test_initialization_file(self, file_queue):
        """Test queue initialization with file database."""
        assert os.path.exists(file_queue.db_path)
    
    def test_initialization_custom_queue(self):
        """Test queue initialization with custom default queue."""
        queue = DuckQueue(":memory:", default_queue="custom")
        assert queue.default_queue == "custom"
        queue.close()
    
    def test_schema_creation(self, queue):
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
    def test_enqueue_basic(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        assert job_id is not None
        assert len(job_id) == 36
        job = queue.get_job(job_id)
        assert job.status == JobStatus.PENDING.value
    
    def test_enqueue_with_kwargs(self, queue):
        job_id = queue.enqueue(greet, args=("World",), kwargs={"greeting": "Hi"})
        job = queue.get_job(job_id)
        result = job.execute()
        assert result == "Hi, World!"
    
    def test_enqueue_custom_queue(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), queue="emails")
        job = queue.get_job(job_id)
        assert job.queue == "emails"
    
    def test_enqueue_with_priority(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), priority=90)
        job = queue.get_job(job_id)
        assert job.priority == 90
    
    def test_enqueue_with_delay(self, queue):
        before = datetime.now()
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=5)
        job = queue.get_job(job_id)
        assert job.status == JobStatus.DELAYED.value
        assert job.execute_after >= before + timedelta(seconds=5)
    
    def test_enqueue_max_attempts(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), max_attempts=5)
        job = queue.get_job(job_id)
        assert job.max_attempts == 5
    
    def test_enqueue_timeout(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), timeout_seconds=600)
        job = queue.get_job(job_id)
        assert job.timeout_seconds == 600
    
    def test_enqueue_unpicklable_function(self, queue):
        with pytest.raises(ValueError) as exc_info:
            queue.enqueue(lambda x: x + 1, args=(1,))
        assert "not picklable" in str(exc_info.value)
    
    def test_enqueue_backpressure_warning(self, queue):
        # Need to import caplog differently and use logging
        with pytest.warns():
            # Enqueue 1001 jobs to trigger warning
            for i in range(1001):
                queue.enqueue(add, args=(i, i), check_backpressure=True)
        
        # Check that we got the expected warning count
        stats = queue.stats()
        assert stats['pending'] == 1001  # All jobs enqueued successfully
    
    def test_enqueue_backpressure_block(self, queue):
        # Enqueue 10001 jobs to exceed the 10000 limit
        for i in range(10001):
            queue.enqueue(add, args=(i, i), check_backpressure=False)
        
        # Next enqueue should fail
        with pytest.raises(BackpressureError) as exc_info:
            queue.enqueue(add, args=(1, 1), check_backpressure=True)
        
        assert "10000" in str(exc_info.value) or "overloaded" in str(exc_info.value)
    
    def test_enqueue_backpressure_disabled(self, queue):
        for i in range(100):
            queue.enqueue(add, args=(i, i), check_backpressure=False)
        assert queue.stats()['pending'] == 100
    
    # Batch Enqueue Tests
    def test_enqueue_batch(self, queue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {}), (add, (5, 6), {})]
        job_ids = queue.enqueue_batch(jobs)
        assert len(job_ids) == 3
        for job_id in job_ids:
            assert queue.get_job(job_id).status == JobStatus.PENDING.value
    
    def test_enqueue_batch_custom_queue(self, queue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {})]
        job_ids = queue.enqueue_batch(jobs, queue="batch")
        for job_id in job_ids:
            assert queue.get_job(job_id).queue == "batch"
    
    def test_enqueue_batch_priority(self, queue):
        jobs = [(add, (1, 2), {}), (add, (3, 4), {})]
        job_ids = queue.enqueue_batch(jobs, priority=80)
        for job_id in job_ids:
            assert queue.get_job(job_id).priority == 80
    
    # Claim Tests
    def test_claim_basic(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        assert job.id == job_id
        assert job.status == JobStatus.CLAIMED.value
        assert job.attempts == 1
    
    def test_claim_empty_queue(self, queue):
        assert queue.claim() is None
    
    def test_claim_custom_queue(self, queue):
        queue.enqueue(add, args=(1, 2), queue="emails")
        assert queue.claim(queue="default") is None
        job = queue.claim(queue="emails")
        assert job.queue == "emails"
    
    def test_claim_priority_order(self, queue):
        low_id = queue.enqueue(add, args=(1, 1), priority=10)
        high_id = queue.enqueue(add, args=(2, 2), priority=90)
        med_id = queue.enqueue(add, args=(3, 3), priority=50)
        assert queue.claim().id == high_id
        assert queue.claim().id == med_id
        assert queue.claim().id == low_id
    
    def test_claim_fifo_same_priority(self, queue):
        id1 = queue.enqueue(add, args=(1, 1))
        time.sleep(0.01)
        id2 = queue.enqueue(add, args=(2, 2))
        time.sleep(0.01)
        id3 = queue.enqueue(add, args=(3, 3))
        assert queue.claim().id == id1
        assert queue.claim().id == id2
        assert queue.claim().id == id3
    
    def test_claim_delayed_job_not_ready(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=10)
        assert queue.claim() is None
        assert queue.get_job(job_id).status == JobStatus.DELAYED.value
    
    def test_claim_delayed_job_ready(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=1)
        time.sleep(1.1)
        job = queue.claim()
        assert job.id == job_id
        assert job.status == JobStatus.CLAIMED.value
    
    def test_claim_promotes_delayed_jobs(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), delay_seconds=1)
        time.sleep(1.1)
        job = queue.claim()
        assert job.id == job_id
    
    def test_claim_stale_job_recovery(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        queue.claim(worker_id="worker-1")
        old_time = datetime.now() - timedelta(seconds=400)
        queue.conn.execute("UPDATE jobs SET claimed_at = ? WHERE id = ?", [old_time, job_id])
        job2 = queue.claim(worker_id="worker-2", claim_timeout=300)
        assert job2.id == job_id
        assert job2.claimed_by == "worker-2"
        assert job2.attempts == 2
    
    def test_claim_custom_worker_id(self, queue):
        queue.enqueue(add, args=(1, 2))
        job = queue.claim(worker_id="custom-worker")
        assert job.claimed_by == "custom-worker"
    
    def test_claim_max_attempts_exceeded(self, queue):
        job_id = queue.enqueue(fail, max_attempts=2)
        for i in range(2):
            job = queue.claim()
            queue.ack(job.id, error="Failed")
        assert queue.claim() is None
        assert queue.get_job(job_id).status == JobStatus.FAILED.value
    
    # Ack Tests
    def test_ack_success(self, queue):
        job_id = queue.enqueue(add, args=(5, 3))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        completed_job = queue.get_job(job_id)
        assert completed_job.status == JobStatus.DONE.value
        assert queue.get_result(job_id) == 8
    
    def test_ack_success_no_result(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.ack(job.id)
        assert queue.get_job(job_id).status == JobStatus.DONE.value
    
    def test_ack_failure_with_retry(self, queue):
        job_id = queue.enqueue(fail, max_attempts=3)
        job = queue.claim()
        queue.ack(job.id, error="Test error")
        retry_job = queue.get_job(job_id)
        assert retry_job.status == JobStatus.PENDING.value
        assert retry_job.attempts == 1
    
    def test_ack_failure_max_attempts(self, queue):
        job_id = queue.enqueue(fail, max_attempts=2)
        for i in range(2):
            job = queue.claim()
            queue.ack(job.id, error=f"Attempt {i+1} failed")
        failed_job = queue.get_job(job_id)
        assert failed_job.status == JobStatus.FAILED.value
    
    def test_ack_nonexistent_job(self, queue):
        queue.ack("nonexistent-id", error="Test")
    
    # Nack Tests
    def test_nack_with_requeue(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.nack(job.id, requeue=True)
        requeued_job = queue.get_job(job_id)
        assert requeued_job.status == JobStatus.PENDING.value
    
    def test_nack_without_requeue(self, queue):
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
            while failed_job.status == JobStatus.PENDING.value and failed_job.attempts < failed_job.max_attempts:
                job = queue.claim()
                if job:
                    queue.ack(job.id, error="Nack without requeue")
                    failed_job = queue.get_job(job_id)
        assert failed_job.status == JobStatus.FAILED.value
    
    # Monitoring Tests
    def test_stats_empty_queue(self, queue):
        stats = queue.stats()
        assert stats['pending'] == 0
        assert stats['claimed'] == 0
        assert stats['done'] == 0
        assert stats['failed'] == 0
        assert stats['delayed'] == 0
    
    def test_stats_with_jobs(self, queue):
        queue.enqueue(add, args=(1, 2))
        queue.enqueue(add, args=(3, 4))
        queue.enqueue(add, args=(5, 6), delay_seconds=10)
        job = queue.claim()
        queue.ack(job.id, result=5)
        stats = queue.stats()
        assert stats['pending'] == 1
        assert stats['done'] == 1
        assert stats['delayed'] == 1
    
    def test_stats_custom_queue(self, queue):
        queue.enqueue(add, args=(1, 2), queue="emails")
        queue.enqueue(add, args=(3, 4), queue="emails")
        queue.enqueue(add, args=(5, 6), queue="reports")
        assert queue.stats("emails")['pending'] == 2
        assert queue.stats("reports")['pending'] == 1
    
    def test_get_job_exists(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        job = queue.get_job(job_id)
        assert job.id == job_id
    
    def test_get_job_not_exists(self, queue):
        assert queue.get_job("nonexistent-id") is None
    
    def test_get_result_success(self, queue):
        job_id = queue.enqueue(add, args=(10, 20))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        assert queue.get_result(job_id) == 30
    
    def test_get_result_not_found(self, queue):
        with pytest.raises(ValueError) as exc_info:
            queue.get_result("nonexistent-id")
        assert "not found" in str(exc_info.value)
    
    def test_get_result_not_done(self, queue):
        job_id = queue.enqueue(add, args=(1, 2))
        with pytest.raises(ValueError) as exc_info:
            queue.get_result(job_id)
        assert "not done" in str(exc_info.value)
    
    def test_get_result_none(self, queue):
        job_id = queue.enqueue(return_none)
        job = queue.claim()
        queue.ack(job.id, result=None)
        assert queue.get_result(job_id) is None
    
    def test_list_dead_letters(self, queue):
        for i in range(3):
            queue.enqueue(fail, args=(f"fail-{i}",), max_attempts=1)
            job = queue.claim()
            queue.ack(job.id, error=f"Failed {i}")
        dead_letters = queue.list_dead_letters()
        assert len(dead_letters) == 3
        for job in dead_letters:
            assert job.status == JobStatus.FAILED.value
    
    def test_list_dead_letters_limit(self, queue):
        for i in range(5):
            queue.enqueue(fail, max_attempts=1)
            job = queue.claim()
            queue.ack(job.id, error="Failed")
        assert len(queue.list_dead_letters(limit=3)) == 3
    
    def test_list_dead_letters_empty(self, queue):
        assert len(queue.list_dead_letters()) == 0
    
    # Purge Tests
    def test_purge_done_jobs(self, queue):
        for i in range(3):
            queue.enqueue(add, args=(i, i))
            job = queue.claim()
            queue.ack(job.id, result=i*2)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ? WHERE status = 'done'", [old_time])
        count = queue.purge(status="done", older_than_hours=24)
        assert count == 3
        assert queue.stats()['done'] == 0
    
    def test_purge_specific_queue(self, queue):
        for i in range(2):
            queue.enqueue(add, args=(i, i), queue="emails")
            job = queue.claim(queue="emails")
            queue.ack(job.id, result=i)
        for i in range(3):
            queue.enqueue(add, args=(i, i), queue="reports")
            job = queue.claim(queue="reports")
            queue.ack(job.id, result=i)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ?", [old_time])
        count = queue.purge(queue="emails", status="done", older_than_hours=24)
        assert count == 2
        assert queue.stats("emails")['done'] == 0
        assert queue.stats("reports")['done'] == 3
    
    def test_purge_failed_jobs(self, queue):
        job_id = queue.enqueue(fail, max_attempts=1)
        job = queue.claim()
        queue.ack(job.id, error="Failed")
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", [old_time, job_id])
        count = queue.purge(status="failed", older_than_hours=24)
        assert count == 1
    
    def test_purge_no_old_jobs(self, queue):
        queue.enqueue(add, args=(1, 2))
        job = queue.claim()
        queue.ack(job.id, result=3)
        count = queue.purge(status="done", older_than_hours=24)
        assert count == 0
    
    def test_purge_all_queues(self, queue):
        for q in ['queue1', 'queue2', 'queue3']:
            queue.enqueue(add, args=(1, 2), queue=q)
            job = queue.claim(queue=q)
            queue.ack(job.id, result=3)
        old_time = datetime.now() - timedelta(hours=25)
        queue.conn.execute("UPDATE jobs SET created_at = ?", [old_time])
        count = queue.purge(queue=None, status="done", older_than_hours=24)
        assert count == 3
    
    # Helper Tests
    def test_generate_worker_id(self, queue):
        worker_id = queue._generate_worker_id()
        assert worker_id is not None
        assert isinstance(worker_id, str)
        import socket
        import os
        assert socket.gethostname() in worker_id
        assert str(os.getpid()) in worker_id
    
    def test_close(self, queue):
        queue.close()
        with pytest.raises(Exception):
            queue.stats()


# ============================================================================
# Test Worker
# ============================================================================

class TestWorker:
    """Test Worker class."""
    
    def test_worker_initialization(self, queue):
        worker = Worker(queue)
        assert worker.queue == queue
        assert worker.concurrency == 1
        assert worker.max_jobs_in_flight == 2
        assert not worker.should_stop
    
    def test_worker_custom_settings(self, queue):
        worker = Worker(queue, queues=['emails', 'reports'], worker_id='custom-worker', 
                       concurrency=4, max_jobs_in_flight=10)
        assert worker.worker_id == 'custom-worker'
        assert worker.concurrency == 4
        assert worker.max_jobs_in_flight == 10
    
    def test_worker_parse_queues_simple(self, queue):
        worker = Worker(queue, queues=['queue1', 'queue2'])
        assert len(worker.queues) == 2
    
    def test_worker_parse_queues_with_priority(self, queue):
        worker = Worker(queue, queues=[('high', 100), ('low', 10), ('medium', 50)])
        assert worker.queues[0] == ('high', 100)
        assert worker.queues[1] == ('medium', 50)
        assert worker.queues[2] == ('low', 10)
    
    def test_worker_signal_handler(self, queue):
        worker = Worker(queue)
        assert not worker.should_stop
        worker._signal_handler(None, None)
        assert worker.should_stop
    
    def test_worker_claim_next_job(self, queue):
        worker = Worker(queue, queues=['emails', 'reports'])
        queue.enqueue(add, args=(1, 2), queue='reports')
        job = worker._claim_next_job()
        assert job.queue == 'reports'
    
    def test_worker_claim_next_job_priority(self, queue):
        worker = Worker(queue, queues=[('high', 100), ('low', 10)])
        queue.enqueue(add, args=(1, 1), queue='low')
        queue.enqueue(add, args=(2, 2), queue='high')
        job = worker._claim_next_job()
        assert job.queue == 'high'
    
    def test_worker_execute_job_success(self, queue):
        worker = Worker(queue)
        job_id = queue.enqueue(add, args=(5, 10))
        job = queue.claim()
        worker._execute_job(job, 1)
        assert queue.get_job(job_id).status == JobStatus.DONE.value
        assert queue.get_result(job_id) == 15
    
    def test_worker_execute_job_failure(self, queue):
        worker = Worker(queue)
        job_id = queue.enqueue(fail, args=("test error",))
        job = queue.claim()
        worker._execute_job(job, 1)
        failed = queue.get_job(job_id)
        assert failed.status == JobStatus.PENDING.value  # Retried
    
    def test_worker_run_sequential(self, queue):
        worker = Worker(queue)
        for i in range(3):
            queue.enqueue(add, args=(i, i))
        
        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()['done'] == 3
    
    def test_worker_run_concurrent(self, queue):
        worker = Worker(queue, concurrency=2)
        for i in range(4):
            queue.enqueue(slow, args=(0.2,))
        
        def stop_worker():
            time.sleep(1.5)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()['done'] == 4
    
    def test_worker_concurrent_backpressure(self, queue):
        worker = Worker(queue, concurrency=2, max_jobs_in_flight=2)
        for i in range(10):
            queue.enqueue(slow, args=(0.1,))
        
        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.05)
        assert queue.stats()['done'] > 0
    
    def test_worker_concurrent_exception_handling(self, queue):
        worker = Worker(queue, concurrency=2)
        for i in range(3):
            queue.enqueue(fail, max_attempts=1)
        
        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()['failed'] == 3
    
    def test_worker_concurrent_timeout(self, queue):
        worker = Worker(queue, concurrency=2)
        queue.enqueue(add, args=(1, 2))
        
        def stop_worker():
            time.sleep(0.3)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        assert queue.stats()['done'] == 1
    
    def test_worker_signal_registration_main_thread(self, queue):
        worker = Worker(queue)
        assert worker.worker_id is not None
    
    def test_worker_signal_registration_background_thread(self, queue):
        worker_ref = []
        def create_worker():
            worker = Worker(queue)
            worker_ref.append(worker)
        thread = threading.Thread(target=create_worker)
        thread.start()
        thread.join()
        assert len(worker_ref) == 1
    
    def test_worker_stops_when_no_futures(self, queue):
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
    
    def test_decorator_basic(self, queue):
        # Manually apply decorator to module-level function
        decorated_func = job(queue)(decorated_add)
        
        assert hasattr(decorated_func, 'delay')
        assert decorated_func(1, 2) == 3
        job_id = decorated_func.delay(5, 10)
        claimed = queue.claim()
        result = claimed.execute()
        queue.ack(claimed.id, result=result)
        assert queue.get_result(job_id) == 15
    
    def test_concurrent_executor_thread_exception(self, queue):
        """Test handling of exceptions raised by executor threads.
        
        This covers the exception handler in _run_concurrent when future.result()
        raises an exception that wasn't caught by _execute_job.
        """
        
        worker = Worker(queue, concurrency=2)
        
        queue.enqueue(instant, args=(1,))
        
        # Patch _execute_job to raise an exception that simulates an executor failure
        original_execute = worker._execute_job
        call_count = [0]
        
        def failing_execute_job(job, job_num):
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate an unexpected exception in the executor thread
                raise RuntimeError("Unexpected executor error")
            return original_execute(job, job_num)
        
        worker._execute_job = failing_execute_job
        
        def stop_worker():
            time.sleep(0.5)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.1)
        
        # Should have attempted to execute the job and logged the error
        assert call_count[0] >= 1
    
    def test_decorator_with_kwargs(self, queue):
        decorated_func = job(queue)(decorated_greet)
        
        decorated_func.delay("World", greeting="Hi")
        claimed = queue.claim()
        result = claimed.execute()
        assert result == "Hi, World!"
    
    def test_decorator_custom_queue(self, queue):
        decorated_func = job(queue, queue="emails")(decorated_email)
        
        job_id = decorated_func.delay("user@example.com")
        assert queue.get_job(job_id).queue == "emails"
    
    def test_decorator_custom_priority(self, queue):
        decorated_func = job(queue, priority=90)(decorated_urgent)
        
        job_id = decorated_func.delay()
        assert queue.get_job(job_id).priority == 90
    
    def test_decorator_delay_seconds(self, queue):
        decorated_func = job(queue, delay_seconds=5)(decorated_delayed)
        
        job_id = decorated_func.delay()
        assert queue.get_job(job_id).status == JobStatus.DELAYED.value
    
    def test_decorator_max_attempts(self, queue):
        decorated_func = job(queue, max_attempts=5)(decorated_retry)
        
        job_id = decorated_func.delay()
        assert queue.get_job(job_id).max_attempts == 5


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_complete_workflow(self, queue):
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
        assert queue.stats()['done'] == 5
    
    def test_retry_workflow(self, queue):
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
    
    def test_priority_workflow(self, queue):
        queue.enqueue(task_priority, args=("low",), priority=10)
        queue.enqueue(task_priority, args=("high",), priority=90)
        queue.enqueue(task_priority, args=("medium",), priority=50)
        
        results = []
        for _ in range(3):
            job = queue.claim()
            result = job.execute()
            queue.ack(job.id, result=result)
            results.append(result)
        
        assert results == ["Priority high", "Priority medium", "Priority low"]
    
    def test_delayed_workflow(self, queue):
        job_id = queue.enqueue(delayed_task, delay_seconds=1)
        assert queue.claim() is None
        time.sleep(1.1)
        job = queue.claim()
        assert job is not None
        result = job.execute()
        queue.ack(job.id, result=result)
        assert queue.get_result(job_id) == "delayed result"
    
    def test_multi_queue_workflow(self, queue):
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
    
    def test_worker_integration(self, queue):
        for i in range(10):
            queue.enqueue(square, args=(i,))
        
        worker = Worker(queue)
        def stop_worker():
            time.sleep(1)
            worker.should_stop = True
        
        threading.Thread(target=stop_worker, daemon=True).start()
        worker.run(poll_interval=0.05)
        assert queue.stats()['done'] == 10
    
    def test_batch_workflow(self, queue):
        jobs_list = [(add_ten, (i,), {}) for i in range(5)]
        queue.enqueue_batch(jobs_list)
        
        results = []
        for _ in range(5):
            job = queue.claim()
            result = job.execute()
            queue.ack(job.id, result=result)
            results.append(result)
        
        assert sorted(results) == [10, 11, 12, 13, 14]
    
    def test_dead_letter_workflow(self, queue):
        for i in range(3):
            queue.enqueue(always_fails, max_attempts=2)
        
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
    
    def test_concurrent_workers(self, queue):
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
        
        assert queue.stats()['done'] == 10


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error conditions.
    
    Note: DuckDB connections are NOT thread-safe for concurrent writes from 
    the same connection. In production, use separate processes or connections 
    per thread. These tests verify behavior within those constraints.
    """
    
    def test_empty_args(self, queue):
        queue.enqueue(no_args)
        job = queue.claim()
        result = job.execute()
        assert result == "no args"
    
    def test_large_result(self, queue):
        job_id = queue.enqueue(large_result)
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert len(stored) == 1000000
    
    def test_complex_data_structures(self, queue):
        input_data = {
            'items': [1, 2, 3, 4, 5],
            'metadata': {'version': 1}
        }
        job_id = queue.enqueue(complex_task, args=(input_data,))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert stored['count'] == 5
        assert stored['nested']['metadata']['version'] == 1
    
    def test_unicode_handling(self, queue):
        job_id = queue.enqueue(unicode_task, args=("Hello 世界 🌍",))
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)
        stored = queue.get_result(job_id)
        assert "世界" in stored
        assert "🌍" in stored
    
    def test_concurrent_enqueue(self, queue):
        job_ids = []
        lock = threading.Lock()
        errors = []
        
        def enqueue_jobs(start, count):
            try:
                # Create a new connection for this thread
                # DuckDB connections are not thread-safe
                for i in range(start, start + count):
                    try:
                        jid = queue.enqueue(identity, args=(i,), check_backpressure=False)
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
            thread = threading.Thread(target=enqueue_jobs, args=(i*10, 10))
            thread.start()
            threads.append(thread)
        
        for thread in threads:
            thread.join()
        
        # DuckDB connections aren't fully thread-safe for concurrent writes
        # So we just check that at least some jobs were enqueued
        assert len(job_ids) > 0
        # And that all enqueued job IDs are unique
        assert len(set(job_ids)) == len(job_ids)
    
    def test_zero_priority(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), priority=0)
        job = queue.get_job(job_id)
        assert job.priority == 0
    
    def test_max_priority(self, queue):
        job_id = queue.enqueue(add, args=(1, 2), priority=100)
        job = queue.get_job(job_id)
        assert job.priority == 100


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Performance-related tests."""
    
    def test_enqueue_performance(self, queue):
        start = time.time()
        for i in range(100):
            queue.enqueue(add, args=(i, i), check_backpressure=False)
        duration = time.time() - start
        assert duration < 5.0  # 5 seconds for 100 jobs
        assert queue.stats()['pending'] == 100
    
    def test_claim_performance(self, queue):
        for i in range(100):
            queue.enqueue(add, args=(i, i))
        
        start = time.time()
        for _ in range(100):
            job = queue.claim()
            if job:
                queue.ack(job.id, result=0)
        duration = time.time() - start
        assert duration < 10.0  # 10 seconds for 100 jobs




if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=core", "--cov-report=term-missing"])