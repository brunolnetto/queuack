# file: test_data_models.py

import pickle

import pytest

from queuack.data_models import BackpressureError, Job
from queuack.status import JobStatus


# Test functions (must be at module level to be picklable)
def add(a, b):
    """Simple addition function."""
    return a + b


def greet(name, greeting="Hello"):
    """Greeting function with kwargs."""
    return f"{greeting}, {name}!"


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
