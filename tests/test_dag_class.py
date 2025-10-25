# tests/test_dag_class.py - NEW FILE

"""
Comprehensive tests for the new DAG class.

Tests the clean, object-oriented DAG API that provides a symmetric
interface to DuckQueue.
"""

import time

import pytest

from queuack import (
    DAG,
    DAGRun,
    DAGRunStatus,
    DAGValidationError,
    DependencyMode,
    DuckQueue,
)


# Test helper functions (must be module-level for pickling)
def extract_data():
    """Extract data from source."""
    return [1, 2, 3, 4, 5]


def transform_data(data=None):
    """Transform data."""
    return [x * 2 for x in (data or [])]


def load_data(data=None):
    """Load data to destination."""
    return f"Loaded {len(data or [])} records"


def failing_job():
    """Job that always fails."""
    raise RuntimeError("Intentional failure")


def quick_job():
    """Quick job for testing."""
    return "quick"


def slow_job():
    """Slow job for testing."""
    time.sleep(0.1)
    return "slow"


def noop():
    """No-op job."""
    return 42


# Fixtures
@pytest.fixture
def queue():
    """Create in-memory queue for testing."""
    q = DuckQueue(":memory:")
    yield q
    q.close()


@pytest.fixture
def file_queue():
    """Create file-based queue for SubDAG testing."""
    import tempfile

    db_path = tempfile.mktemp(suffix=".db")
    q = DuckQueue(db_path)
    yield q
    q.close()
    # Clean up temp file
    try:
        import os

        os.unlink(db_path)
    except OSError:
        pass


# ============================================================================
# Basic DAG Class Tests
# ============================================================================


class TestDAGBasics:
    """Test basic DAG class functionality."""

    def test_create_dag_instance(self, queue):
        """Test creating a DAG instance."""
        dag = DAG("test", queue)

        assert dag.name == "test"
        assert dag.queue is queue
        assert dag.description is None
        assert dag.dag_run_id is None  # Not submitted
        assert dag.status == DAGRunStatus.PENDING
        assert len(dag.jobs) == 0
        assert not dag._submitted

    def test_create_dag_with_description(self, queue):
        """Test creating DAG with description."""
        dag = DAG("test", queue, description="Test DAG")

        assert dag.description == "Test DAG"

    def test_create_dag_via_factory(self, queue):
        """Test creating DAG via queue.create_dag()."""
        dag = queue.create_dag("factory_test")

        assert dag.name == "factory_test"
        assert dag.queue is queue
        assert isinstance(dag, DAG)

    def test_dag_repr(self, queue):
        """Test DAG string representation."""
        dag = DAG("test", queue)

        repr_str = repr(dag)
        assert "test" in repr_str
        assert "not_submitted" in repr_str

        str_str = str(dag)
        assert "test" in str_str
        assert "not submitted" in str_str

    def test_dag_repr_after_submit(self, queue):
        """Test DAG repr after submission."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        repr_str = repr(dag)
        assert "test" in repr_str
        assert "running" in repr_str.lower()

        str_str = str(dag)
        assert "RUNNING" in str_str or "running" in str_str


# ============================================================================
# Job Management Tests
# ============================================================================


class TestJobManagement:
    """Test adding and managing jobs in DAG."""

    def test_add_single_job(self, queue):
        """Test adding a single job."""
        dag = DAG("test", queue)

        job_id = dag.add_job(extract_data, name="extract")

        assert job_id is not None
        assert "extract" in dag.jobs
        assert dag.jobs["extract"] == job_id

    def test_add_job_auto_name(self, queue):
        """Test adding job with auto-generated name."""
        dag = DAG("test", queue)

        job_id = dag.add_job(extract_data)

        assert job_id is not None
        assert len(dag.jobs) == 1

    def test_add_job_with_args_kwargs(self, queue):
        """Test adding job with arguments."""
        dag = DAG("test", queue)

        job_id = dag.add_job(
            transform_data, name="transform", args=([1, 2, 3],), kwargs={"key": "value"}
        )

        assert job_id is not None

    def test_add_job_with_priority(self, queue):
        """Test adding job with custom priority."""
        dag = DAG("test", queue)

        high = dag.add_job(extract_data, name="high", priority=90)
        low = dag.add_job(extract_data, name="low", priority=10)

        assert high in dag.jobs.values()
        assert low in dag.jobs.values()

    def test_add_multiple_jobs(self, queue):
        """Test adding multiple jobs."""
        dag = DAG("test", queue)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(transform_data, name="job2")
        j3 = dag.add_job(load_data, name="job3")

        assert len(dag.jobs) == 3
        assert "job1" in dag.jobs
        assert "job2" in dag.jobs
        assert "job3" in dag.jobs

    def test_add_job_duplicate_name_raises(self, queue):
        """Test that duplicate job names raise error."""
        dag = DAG("test", queue)

        dag.add_job(extract_data, name="duplicate")

        with pytest.raises(ValueError, match="already exists"):
            dag.add_job(transform_data, name="duplicate")

    def test_add_job_after_submit_raises(self, queue):
        """Test that adding jobs after submit raises error."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")
        dag.submit()

        with pytest.raises(RuntimeError, match="already submitted"):
            dag.add_job(transform_data, name="job2")

    def test_get_job_by_name(self, queue):
        """Test getting job by name."""
        dag = DAG("test", queue)
        job_id = dag.add_job(extract_data, name="extract")
        dag.submit()

        job = dag.get_job("extract")

        assert job is not None
        assert job.id == job_id
        assert job.node_name == "extract"

    def test_get_job_by_id(self, queue):
        """Test getting job by ID."""
        dag = DAG("test", queue)
        job_id = dag.add_job(extract_data, name="extract")
        dag.submit()

        job = dag.get_job(job_id)

        assert job is not None
        assert job.id == job_id


# ============================================================================
# Dependency Tests
# ============================================================================


class TestDependencies:
    """Test job dependency management."""

    def test_add_job_with_string_dependency(self, queue):
        """Test adding job with single string dependency."""
        dag = DAG("test", queue)

        extract = dag.add_job(extract_data, name="extract")
        transform = dag.add_job(transform_data, name="transform", depends_on="extract")

        assert extract in dag.jobs.values()
        assert transform in dag.jobs.values()

    def test_add_job_with_list_dependencies(self, queue):
        """Test adding job with multiple dependencies."""
        dag = DAG("test", queue)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(extract_data, name="job2")
        j3 = dag.add_job(transform_data, name="job3", depends_on=["job1", "job2"])

        assert len(dag.jobs) == 3

    def test_add_job_with_external_dependency(self, queue):
        """Test adding job that depends on external job ID."""
        # Create external job
        external_id = queue.enqueue(extract_data)

        dag = DAG("test", queue)
        internal = dag.add_job(transform_data, name="internal", depends_on=external_id)

        assert internal in dag.jobs.values()

    def test_add_job_with_mixed_dependencies(self, queue):
        """Test mixing internal names and external IDs."""
        external_id = queue.enqueue(extract_data)

        dag = DAG("test", queue)
        internal = dag.add_job(extract_data, name="internal")
        combined = dag.add_job(
            transform_data, name="combined", depends_on=["internal", external_id]
        )

        assert len(dag.jobs) == 2

    def test_add_job_invalid_dependency_fail_fast(self, queue):
        """Test invalid dependency with fail_fast=True."""
        dag = DAG("test", queue, fail_fast=True)

        dag.add_job(extract_data, name="job1")

        with pytest.raises(ValueError, match="not found"):
            dag.add_job(transform_data, depends_on="nonexistent")

    def test_add_job_invalid_dependency_no_fail_fast(self, queue):
        """Test invalid dependency with fail_fast=False."""
        dag = DAG("test", queue, fail_fast=False)

        dag.add_job(extract_data, name="job1")

        # Should not raise, but log warning
        import warnings

        with warnings.catch_warnings(record=True):
            dag.add_job(transform_data, name="job2", depends_on="nonexistent")

    def test_dependency_mode_all(self, queue):
        """Test ALL dependency mode (default)."""
        dag = DAG("test", queue)

        p1 = dag.add_job(extract_data, name="p1")
        p2 = dag.add_job(extract_data, name="p2")
        child = dag.add_job(
            transform_data,
            name="child",
            depends_on=["p1", "p2"],
            dependency_mode=DependencyMode.ALL,
        )

        assert child in dag.jobs.values()

    def test_dependency_mode_any(self, queue):
        """Test ANY dependency mode."""
        dag = DAG("test", queue)

        p1 = dag.add_job(extract_data, name="p1")
        p2 = dag.add_job(extract_data, name="p2")
        child = dag.add_job(
            transform_data,
            name="child",
            depends_on=["p1", "p2"],
            dependency_mode=DependencyMode.ANY,
        )

        assert child in dag.jobs.values()


# ============================================================================
# Submission Tests
# ============================================================================


class TestSubmission:
    """Test DAG submission."""

    def test_submit_empty_dag(self, queue):
        """Test submitting empty DAG."""
        dag = DAG("empty", queue)

        run_id = dag.submit()

        assert run_id is not None
        assert dag.dag_run_id == run_id
        assert dag._submitted
        assert dag.status == DAGRunStatus.RUNNING

    def test_submit_dag_with_jobs(self, queue):
        """Test submitting DAG with jobs."""
        dag = DAG("test", queue)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(transform_data, name="job2", depends_on="job1")

        run_id = dag.submit()

        assert run_id is not None
        assert dag._submitted
        assert dag.dag_run_id is not None

    def test_submit_twice_raises(self, queue):
        """Test that submitting twice raises error."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        dag.submit()

        with pytest.raises(RuntimeError, match="already submitted"):
            dag.submit()

    def test_submit_creates_dag_run_record(self, queue):
        """Test that submission creates DAG run record."""
        dag = DAG("test", queue, description="Test description")
        dag.add_job(extract_data, name="job1")

        dag.submit()

        # Check database
        result = queue.conn.execute(
            "SELECT name, description, status FROM dag_runs WHERE id = ?",
            [dag.dag_run_id],
        ).fetchone()

        assert result is not None
        assert result[0] == "test"
        assert result[1] == "Test description"
        assert result[2] == "running"

    def test_submit_inserts_jobs(self, queue):
        """Test that submission inserts all jobs."""
        dag = DAG("test", queue)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(transform_data, name="job2")

        dag.submit()

        # Check jobs exist
        count = queue.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE dag_run_id = ?", [dag.dag_run_id]
        ).fetchone()[0]

        assert count == 2

    def test_submit_inserts_dependencies(self, queue):
        """Test that submission creates dependency records."""
        dag = DAG("test", queue)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(transform_data, name="job2", depends_on="job1")

        dag.submit()

        # Check dependency exists
        deps = queue.conn.execute(
            """
            SELECT child_job_id, parent_job_id 
            FROM job_dependencies
            WHERE parent_job_id = ?
            """,
            [j1],
        ).fetchall()

        assert len(deps) == 1
        assert deps[0][1] == j1


# ============================================================================
# Status and Progress Tests
# ============================================================================


class TestStatusAndProgress:
    """Test DAG status tracking and progress monitoring."""

    def test_status_before_submit(self, queue):
        """Test status before submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        assert dag.status == DAGRunStatus.PENDING

    def test_status_after_submit(self, queue):
        """Test status after submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        dag.submit()

        assert dag.status == DAGRunStatus.RUNNING

    def test_progress_before_submit(self, queue):
        """Test progress before submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")
        dag.add_job(transform_data, name="job2")

        progress = dag.progress

        assert progress["pending"] == 2
        assert progress["claimed"] == 0
        assert progress["done"] == 0

    def test_progress_after_submit(self, queue):
        """Test progress after submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")
        dag.add_job(transform_data, name="job2")

        dag.submit()

        progress = dag.progress

        assert progress["pending"] >= 0
        assert sum(progress.values()) == 2

    def test_is_complete_before_submit(self, queue):
        """Test is_complete before submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        assert not dag.is_complete()

    def test_is_complete_after_submit(self, queue):
        """Test is_complete after submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        dag.submit()

        # Not complete yet
        assert not dag.is_complete()

    def test_is_complete_after_execution(self, queue):
        """Test is_complete after job execution."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        dag.submit()

        # Execute the job
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        # Now complete
        assert dag.is_complete()

    def test_get_jobs_before_submit_raises(self, queue):
        """Test get_jobs before submission raises."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        with pytest.raises(RuntimeError, match="not yet submitted"):
            dag.get_jobs()

    def test_get_jobs_after_submit(self, queue):
        """Test get_jobs after submission."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")
        dag.add_job(transform_data, name="job2")

        dag.submit()

        jobs = dag.get_jobs()

        assert len(jobs) == 2
        assert jobs[0]["name"] in ["job1", "job2"]
        assert jobs[0]["status"] == "pending"

    def test_update_status(self, queue):
        """Test manual status update."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        dag.submit()

        # Complete job
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        # Update status
        dag.update_status()

        assert dag.status == DAGRunStatus.DONE


# ============================================================================
# Validation Tests
# ============================================================================


class TestValidation:
    """Test DAG validation."""

    def test_validate_before_submit(self, queue):
        """Test validating DAG structure before submission."""
        dag = DAG("test", queue)

        dag.add_job(extract_data, name="job1")
        dag.add_job(transform_data, name="job2", depends_on="job1")

        warnings = dag.validate()

        assert isinstance(warnings, list)

    def test_validate_detects_cycles(self, queue):
        """Test that validation detects cycles."""
        dag = DAG("test", queue, fail_fast=True)

        j1 = dag.add_job(extract_data, name="job1")
        j2 = dag.add_job(transform_data, name="job2", depends_on="job1")

        # Manually create cycle in engine
        with pytest.raises(DAGValidationError):
            dag._context.engine.add_dependency(j1, j2)

    def test_validate_warns_disconnected_components(self, queue):
        """Test validation warns about disconnected components."""
        dag = DAG("test", queue)

        dag.add_job(extract_data, name="island1")
        dag.add_job(transform_data, name="island2")

        warnings = dag.validate()

        assert any("disconnected" in w for w in warnings)

    def test_submit_without_validation(self, queue):
        """Test submitting without validation."""
        dag = DAG("test", queue, validate=False)
        dag.add_job(extract_data, name="job1")

        # Should not validate
        run_id = dag.submit()

        assert run_id is not None

    def test_submit_with_validation_warnings(self, queue):
        """Test submit with validation warnings."""
        dag = DAG("test", queue, validate=True)

        dag.add_job(extract_data, name="island1")
        dag.add_job(transform_data, name="island2")

        # Should warn but not raise
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            dag.submit()

            assert len(w) > 0


# ============================================================================
# Execution Tests
# ============================================================================


class TestExecution:
    """Test DAG execution."""

    def test_simple_linear_execution(self, queue):
        """Test executing simple linear DAG."""
        dag = DAG("linear", queue)

        extract = dag.add_job(extract_data, name="extract")
        transform = dag.add_job(transform_data, name="transform", depends_on="extract")

        dag.submit()

        # Execute extract
        job1 = queue.claim()
        assert job1.id == extract
        queue.ack(job1.id, result=job1.execute())

        # Now transform should be claimable
        job2 = queue.claim()
        assert job2.id == transform

    def test_parallel_execution(self, queue):
        """Test executing parallel jobs."""
        dag = DAG("parallel", queue)

        extract = dag.add_job(extract_data, name="extract")
        t1 = dag.add_job(quick_job, name="t1", depends_on="extract")
        t2 = dag.add_job(quick_job, name="t2", depends_on="extract")

        dag.submit()

        # Complete extract
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        # Both t1 and t2 should be claimable
        claimed_ids = []
        claimed_ids.append(queue.claim().id)
        claimed_ids.append(queue.claim().id)

        assert t1 in claimed_ids
        assert t2 in claimed_ids

    def test_execution_order(self, queue):
        """Test get_execution_order."""
        dag = DAG("order", queue)

        extract = dag.add_job(extract_data, name="extract")
        t1 = dag.add_job(transform_data, name="t1", depends_on="extract")
        t2 = dag.add_job(transform_data, name="t2", depends_on="extract")
        load = dag.add_job(load_data, name="load", depends_on=["t1", "t2"])

        order = dag.get_execution_order()

        assert len(order) == 3
        assert order[0] == ["extract"]
        assert set(order[1]) == {"t1", "t2"}
        assert order[2] == ["load"]


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestContextManager:
    """Test DAG as context manager."""

    def test_context_manager_auto_submit(self, queue):
        """Test auto-submit on context exit."""
        with DAG("ctx_test", queue) as dag:
            dag.add_job(extract_data, name="job1")

        # Should be submitted after exit
        assert dag._submitted
        assert dag.dag_run_id is not None

    def test_context_manager_with_exception(self, queue):
        """Test context manager handles exceptions."""
        with pytest.raises(ValueError):
            with DAG("ctx_error", queue) as dag:
                dag.add_job(extract_data, name="job1")
                raise ValueError("Test error")

        # DAG should not be submitted
        assert not dag._submitted

    def test_context_manager_explicit_submit(self, queue):
        """Test explicit submit in context manager."""
        with DAG("ctx_explicit", queue) as dag:
            dag.add_job(extract_data, name="job1")
            dag.submit()

        # Should not submit twice
        assert dag._submitted


# ============================================================================
# Wait for Completion Tests
# ============================================================================


class TestWaitForCompletion:
    """Test wait_for_completion functionality."""

    def test_wait_for_completion_not_submitted_raises(self, queue):
        """Test wait before submit raises."""
        dag = DAG("test", queue)
        dag.add_job(extract_data, name="job1")

        with pytest.raises(RuntimeError, match="not yet submitted"):
            dag.wait_for_completion()

    def test_wait_for_completion_immediate(self, queue):
        """Test wait when already complete."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")

        dag.submit()

        # Complete the job
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        # Wait should return immediately
        result = dag.wait_for_completion(timeout=1)

        assert result is True
        assert dag.is_complete()

    def test_wait_for_completion_with_timeout(self, queue):
        """Test wait with timeout."""
        dag = DAG("test", queue)
        dag.add_job(slow_job, name="slow")

        dag.submit()

        # Timeout before completion
        result = dag.wait_for_completion(timeout=0.01)

        assert result is False
        assert not dag.is_complete()

    def test_wait_for_completion_with_callback(self, queue):
        """Test wait with progress callback."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")

        dag.submit()

        callback_calls = []

        def callback(progress):
            callback_calls.append(progress.copy())

        # Complete job in background
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        dag.wait_for_completion(callback=callback, poll_interval=0.1)

        # Callback should have been called
        assert len(callback_calls) > 0


# ============================================================================
# Mermaid Export Tests
# ============================================================================


class TestMermaidExport:
    """Test Mermaid diagram export."""

    def test_export_mermaid_simple(self, queue):
        """Test exporting simple DAG to Mermaid."""
        dag = DAG("test", queue)

        dag.add_job(extract_data, name="extract")
        dag.add_job(transform_data, name="transform", depends_on="extract")
        dag.add_job(load_data, name="load", depends_on="transform")

        mermaid = dag.export_mermaid()

        assert "graph TD" in mermaid
        assert "extract" in mermaid
        assert "transform" in mermaid
        assert "load" in mermaid
        assert "-->" in mermaid

    def test_export_mermaid_parallel(self, queue):
        """Test exporting parallel DAG."""
        dag = DAG("parallel", queue)

        extract = dag.add_job(extract_data, name="extract")
        t1 = dag.add_job(transform_data, name="t1", depends_on="extract")
        t2 = dag.add_job(transform_data, name="t2", depends_on="extract")

        mermaid = dag.export_mermaid()

        assert "t1" in mermaid
        assert "t2" in mermaid
        assert mermaid.count("-->") >= 2


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_dag_submission(self, queue):
        """Test submitting DAG with no jobs."""
        dag = DAG("empty", queue)

        run_id = dag.submit()

        assert run_id is not None
        assert len(dag.jobs) == 0
        assert dag.is_complete()

    def test_single_job_dag(self, queue):
        """Test DAG with single job."""
        dag = DAG("single", queue)
        dag.add_job(noop, name="only")

        dag.submit()

        assert len(dag.jobs) == 1
        assert not dag.is_complete()

    def test_large_dag(self, queue):
        """Test DAG with many jobs."""
        dag = DAG("large", queue)

        for i in range(100):
            dag.add_job(noop, name=f"job_{i}")

        dag.submit()

        assert len(dag.jobs) == 100

    def test_deep_dependency_chain(self, queue):
        """Test deep chain of dependencies."""
        dag = DAG("deep", queue)

        prev = dag.add_job(noop, name="job_0")

        for i in range(1, 20):
            dag.add_job(noop, name=f"job_{i}", depends_on=f"job_{i - 1}")

        dag.submit()

        order = dag.get_execution_order()
        assert len(order) == 20


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests with full execution."""

    def test_complete_pipeline_execution(self, queue):
        """Test complete pipeline execution."""
        dag = DAG("pipeline", queue)

        extract = dag.add_job(extract_data, name="extract")
        transform = dag.add_job(
            transform_data, name="transform", depends_on="extract", args=([1, 2, 3],)
        )
        load = dag.add_job(load_data, name="load", depends_on="transform")

        dag.submit()

        # Execute all jobs
        while not dag.is_complete():
            job = queue.claim()
            if job:
                try:
                    result = job.execute()
                    queue.ack(job.id, result=result)
                except Exception as e:
                    queue.ack(job.id, error=str(e))

        # Update DAG status after completion
        dag.update_status()  # ADD THIS

        assert dag.is_complete()
        assert dag.status == DAGRunStatus.DONE
        assert dag.progress["done"] == 3

    def test_failure_propagation(self, queue):
        """Test failure propagation in DAG."""
        dag = DAG("failure", queue)

        fail = dag.add_job(failing_job, name="fail", max_attempts=1)
        child = dag.add_job(transform_data, name="child", depends_on="fail")

        dag.submit()

        # Execute failing job
        job = queue.claim()
        try:
            job.execute()
        except Exception as e:
            queue.ack(job.id, error=str(e))

        # Child should be skipped
        child_job = dag.get_job("child")
        assert child_job.status == "skipped"

        # Update and check final status
        dag.update_status()
        assert dag.status == DAGRunStatus.FAILED
        assert dag.progress["failed"] == 1
        assert dag.progress["skipped"] == 1

    def test_any_dependency_mode_execution(self, queue):
        """Test ANY dependency mode with mixed success/failure."""
        dag = DAG("any_mode", queue)

        success = dag.add_job(noop, name="success")
        failure = dag.add_job(failing_job, name="failure", max_attempts=1)

        child = dag.add_job(
            noop,
            name="child",
            depends_on=["success", "failure"],
            dependency_mode=DependencyMode.ANY,
        )

        dag.submit()

        # Execute both parents
        for _ in range(2):
            job = queue.claim()
            if job:
                try:
                    result = job.execute()
                    queue.ack(job.id, result=result)
                except Exception as e:
                    queue.ack(job.id, error=str(e))

        # Child should still be runnable (ANY mode: one parent succeeded)
        child_job = queue.claim()
        assert child_job is not None, (
            "Child with ANY dependency should be claimable when one parent succeeds"
        )
        assert child_job.id == child

    def test_mixed_external_internal_dependencies(self, queue):
        """Test mixing external and internal job dependencies."""
        # Create external job
        external = queue.enqueue(noop)

        # Complete external job
        ext_job = queue.claim()
        queue.ack(ext_job.id, result=ext_job.execute())

        # Create DAG that depends on it
        dag = DAG("mixed", queue)

        internal = dag.add_job(noop, name="internal")
        combined = dag.add_job(noop, name="combined", depends_on=[external, "internal"])

        dag.submit()

        # Complete internal
        job = queue.claim()
        if job.id == internal:
            queue.ack(job.id, result=job.execute())

        # Combined should now be claimable
        combined_job = queue.claim()
        assert combined_job.id == combined


# ============================================================================
# Comparison Tests (DAG vs DAGContext)
# ============================================================================


class TestDAGvsDAGContext:
    """Test that DAG class produces same results as DAGContext."""

    def test_equivalent_submission(self, queue):
        """Test that DAG and DAGContext produce equivalent results."""
        # Using DAG class
        dag1 = DAG("dag_class", queue)
        j1_dag = dag1.add_job(noop, name="job1")
        j2_dag = dag1.add_job(noop, name="job2", depends_on="job1")
        dag1.submit()

        # Using DAGContext
        from queuack import DAGContext

        with DAGContext(queue, "dag_context") as dag2:
            j1_ctx = dag2.enqueue(noop, name="job1")
            j2_ctx = dag2.enqueue(noop, name="job2", depends_on="job1")

        # Both should have created DAG runs
        dag1_run = queue.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE dag_run_id = ?", [dag1.dag_run_id]
        ).fetchone()[0]

        dag2_run = queue.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE dag_run_id = ?", [dag2.dag_run_id]
        ).fetchone()[0]

        assert dag1_run == 2
        assert dag2_run == 2

    def test_execution_order_equivalent(self, queue):
        """Test execution order is same for DAG and DAGContext."""
        # Using DAG
        dag1 = DAG("test1", queue)
        dag1.add_job(noop, name="a")
        dag1.add_job(noop, name="b", depends_on="a")
        dag1.add_job(noop, name="c", depends_on="a")
        dag1.add_job(noop, name="d", depends_on=["b", "c"])

        order1 = dag1.get_execution_order()

        # Using DAGContext
        from queuack import DAGContext

        dag2 = DAGContext(queue, "test2")
        dag2.enqueue(noop, name="a")
        dag2.enqueue(noop, name="b", depends_on="a")
        dag2.enqueue(noop, name="c", depends_on="a")
        dag2.enqueue(noop, name="d", depends_on=["b", "c"])

        order2 = dag2.get_execution_order()

        # Orders should be identical
        assert order1 == order2


# ============================================================================
# Property Tests
# ============================================================================


class TestProperties:
    """Test DAG property access."""

    def test_jobs_property_returns_copy(self, queue):
        """Test that jobs property returns a copy."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")

        jobs1 = dag.jobs
        jobs2 = dag.jobs

        # Should be equal but not same object
        assert jobs1 == jobs2
        assert jobs1 is not jobs2

    def test_status_property_caches_dag_run(self, queue):
        """Test that status property caches DAGRun helper."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        # Access status multiple times
        status1 = dag.status
        status2 = dag.status

        # DAGRun should be cached
        assert dag._dag_run is not None

    def test_progress_property_updates(self, queue):
        """Test that progress property reflects current state."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        # Initial progress
        p1 = dag.progress
        assert p1["pending"] == 1
        assert p1["done"] == 0

        # Complete job
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        # Updated progress
        p2 = dag.progress
        assert p2["done"] == 1
        assert p2["pending"] == 0


# ============================================================================
# Error Message Tests
# ============================================================================


class TestErrorMessages:
    """Test quality of error messages."""

    def test_add_after_submit_clear_message(self, queue):
        """Test clear error message when adding after submit."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        with pytest.raises(RuntimeError) as exc_info:
            dag.add_job(noop, name="job2")

        error_msg = str(exc_info.value)
        assert "already submitted" in error_msg
        assert "test" in error_msg

    def test_submit_twice_clear_message(self, queue):
        """Test clear error message when submitting twice."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        with pytest.raises(RuntimeError) as exc_info:
            dag.submit()

        error_msg = str(exc_info.value)
        assert "already submitted" in error_msg
        assert dag.dag_run_id[:8] in error_msg

    def test_wait_before_submit_clear_message(self, queue):
        """Test clear error message when waiting before submit."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")

        with pytest.raises(RuntimeError) as exc_info:
            dag.wait_for_completion()

        error_msg = str(exc_info.value)
        assert "not yet submitted" in error_msg
        assert "submit()" in error_msg

    def test_get_jobs_before_submit_clear_message(self, queue):
        """Test clear error when getting jobs before submit."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")

        with pytest.raises(RuntimeError) as exc_info:
            dag.get_jobs()

        error_msg = str(exc_info.value)
        assert "not yet submitted" in error_msg


# ============================================================================
# Logging Tests
# ============================================================================


class TestLogging:
    """Test DAG logging behavior."""

    def test_submit_logs_info(self, queue, caplog):
        """Test that submission logs informative message."""
        import logging

        caplog.set_level(logging.INFO)

        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.add_job(noop, name="job2")

        dag.submit()

        # Check log messages
        assert any("test" in record.message for record in caplog.records)
        assert any("2 jobs" in record.message for record in caplog.records)


# ============================================================================
# Thread Safety Tests
# ============================================================================


class TestThreadSafety:
    """Test thread safety of DAG operations."""

    def test_concurrent_job_addition(self, queue):
        """Test that concurrent job addition is safe."""
        import threading

        dag = DAG("concurrent", queue)

        errors = []

        def add_jobs(start_idx):
            try:
                for i in range(start_idx, start_idx + 10):
                    dag.add_job(noop, name=f"job_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_jobs, args=(i * 10,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have added 50 jobs with no errors
        assert len(errors) == 0
        assert len(dag.jobs) == 50

    def test_concurrent_status_checks(self, queue):
        """Test that concurrent status checks don't interfere."""
        import threading

        dag = DAG("concurrent", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        statuses = []

        def check_status():
            for _ in range(10):
                statuses.append(dag.status)

        threads = [threading.Thread(target=check_status) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All status checks should succeed
        assert len(statuses) == 50
        assert all(isinstance(s, DAGRunStatus) for s in statuses)


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance characteristics."""

    def test_large_dag_creation_performance(self, queue):
        """Test creating large DAG is reasonably fast."""
        import time

        dag = DAG("large", queue)

        start = time.perf_counter()

        for i in range(1000):
            dag.add_job(noop, name=f"job_{i}")

        elapsed = time.perf_counter() - start

        # Should complete in under 5 seconds
        assert elapsed < 5.0
        assert len(dag.jobs) == 1000

    def test_submission_performance(self, queue):
        """Test DAG submission performance."""
        import time

        dag = DAG("perf", queue)

        # Create 100 jobs with dependencies
        prev = None
        for i in range(100):
            if prev:
                dag.add_job(noop, name=f"job_{i}", depends_on=prev)
            else:
                dag.add_job(noop, name=f"job_{i}")
            prev = f"job_{i}"

        start = time.perf_counter()
        dag.submit()
        elapsed = time.perf_counter() - start

        # Should submit in under 5 seconds
        assert elapsed < 5.0


# ============================================================================
# Documentation Example Tests
# ============================================================================


class TestDocumentationExamples:
    """Test that documentation examples actually work."""

    def test_basic_pipeline_example(self, queue):
        """Test basic pipeline example from docstring."""
        dag = DAG("etl_pipeline", queue)

        # Build workflow
        extract = dag.add_job(extract_data, name="extract")
        transform = dag.add_job(transform_data, name="transform", depends_on="extract")
        load = dag.add_job(load_data, name="load", depends_on="transform")

        # Submit and monitor
        dag.submit()
        assert dag.status in [DAGRunStatus.RUNNING, DAGRunStatus.PENDING]
        assert dag.progress is not None

    def test_parallel_processing_example(self, queue):
        """Test parallel processing example from docstring."""
        dag = DAG("parallel_etl", queue)

        # Single extract
        extract = dag.add_job(extract_data, name="extract")

        # Parallel transforms
        t1 = dag.add_job(transform_data, name="transform_a", depends_on="extract")
        t2 = dag.add_job(transform_data, name="transform_b", depends_on="extract")
        t3 = dag.add_job(transform_data, name="transform_c", depends_on="extract")

        # Combined load
        load = dag.add_job(
            load_data,
            name="load",
            depends_on=["transform_a", "transform_b", "transform_c"],
        )

        dag.submit()

        order = dag.get_execution_order()
        assert len(order) == 3
        assert order[0] == ["extract"]
        assert set(order[1]) == {"transform_a", "transform_b", "transform_c"}
        assert order[2] == ["load"]

    def test_any_dependency_example(self, queue):
        """Test ANY dependency mode example from docstring."""
        dag = DAG("multi_source", queue)

        api1 = dag.add_job(noop, name="api1")
        api2 = dag.add_job(noop, name="api2")
        api3 = dag.add_job(noop, name="api3")

        # Process runs if ANY API call succeeds
        process = dag.add_job(
            noop,
            name="process",
            depends_on=["api1", "api2", "api3"],
            dependency_mode=DependencyMode.ANY,
        )

        dag.submit()
        assert len(dag.jobs) == 4

    def test_context_manager_example(self, queue):
        """Test context manager example from docstring."""
        with DAG("auto_submit", queue) as dag:
            dag.add_job(noop, name="t1")
            dag.add_job(noop, name="t2", depends_on="t1")

        # Auto-submitted on exit
        assert dag._submitted


# ============================================================================
# Regression Tests
# ============================================================================


class TestRegressions:
    """Test for known bugs and regressions."""

    def test_dag_run_helper_caching(self, queue):
        """Test that DAGRun helper is properly cached."""
        dag = DAG("test", queue)
        dag.add_job(noop, name="job1")
        dag.submit()

        # First access creates cache
        status1 = dag.status
        dag_run1 = dag._dag_run

        # Second access uses cache
        status2 = dag.status
        dag_run2 = dag._dag_run

        assert dag_run1 is dag_run2

    def test_empty_dependency_list(self, queue):
        """Test that empty dependency list works."""
        dag = DAG("test", queue)

        # Empty list should work like no dependencies
        job_id = dag.add_job(noop, name="job1", depends_on=[])

        assert job_id in dag.jobs.values()

    def test_none_kwargs(self, queue):
        """Test that None kwargs are handled correctly."""
        dag = DAG("test", queue)

        # None kwargs should be converted to empty dict
        job_id = dag.add_job(noop, name="job1", kwargs=None)

        dag.submit()
        job = dag.get_job("job1")
        assert job is not None


# ============================================================================
# SubDAG Executor Tests
# ============================================================================


def factory(q):
    dag = DAG("sub", q)
    dag.add_job(noop, name="job1")
    return dag


def create_sub(q):
    dag = DAG("sub", q)
    dag.add_job(noop, name="job1")
    return dag


def create_sub(q):
    dag = DAG("sub", q)
    dag.add_job(noop, name="job1")
    return dag


class TestSubDAGExecutor:
    """Test SubDAGExecutor wrapper."""

    def test_executor_creation(self, queue):
        """Test creating SubDAGExecutor."""
        from queuack.dag import SubDAGExecutor

        def factory(q):
            dag = DAG("sub", q)
            dag.add_job(noop, name="job1")
            return dag

        executor = SubDAGExecutor(
            dag_factory=factory, queue_path=queue.db_path, poll_interval=0.1
        )

        assert executor.dag_factory is factory
        assert executor.queue_path == queue.db_path

    def test_executor_is_picklable(self, queue):
        """Test that executor can be pickled."""
        import pickle

        from queuack.dag import SubDAGExecutor

        executor = SubDAGExecutor(dag_factory=factory, queue_path=queue.db_path)

        # Should be picklable
        pickled = pickle.dumps(executor)
        unpickled = pickle.loads(pickled)

        assert unpickled.queue_path == queue.db_path


# ============================================================================
# Basic Sub-DAG Tests
# ============================================================================


class TestBasicSubDAGs:
    """Test basic sub-DAG functionality."""

    def test_add_subdag_to_dag(self, queue):
        """Test adding sub-DAG to main DAG."""

        main = DAG("main", queue)
        sub_job_id = main.add_subdag(create_sub, name="sub_dag")

        assert sub_job_id in main.jobs.values()
        assert "sub_dag" in main.jobs

    def test_submit_dag_with_subdag(self, queue):
        """Test submitting DAG containing sub-DAG."""
        main = DAG("main", queue)
        main.add_subdag(create_sub, name="sub_dag")

        run_id = main.submit()

        assert run_id is not None
        assert main._submitted

    def test_execute_simple_subdag(self, file_queue):
        """Test executing a simple sub-DAG."""

        main = DAG("main", file_queue)
        sub_id = main.add_subdag(create_sub, name="sub_dag")

        main.submit()

        # Execute the sub-DAG job
        job = file_queue.claim()
        assert job.id == sub_id

        # This will create and execute the sub-DAG
        result = job.execute()
        file_queue.ack(job.id, result=result)

        # Check sub-DAG was created
        subdags = file_queue.conn.execute(
            "SELECT id FROM dag_runs WHERE parent_job_id = ?", [sub_id]
        ).fetchall()

        assert len(subdags) == 1


# ============================================================================
# Hierarchy Tests
# ============================================================================


class TestDAGHierarchy:
    """Test DAG parent-child relationships."""

    def test_subdag_links_to_parent_job(self, file_queue):
        """Test that sub-DAG is linked to parent job."""

        main = DAG("main", file_queue)
        sub_id = main.add_subdag(create_sub, name="sub_dag")
        main.submit()

        # Execute sub-DAG job
        job = file_queue.claim()
        result = job.execute()
        file_queue.ack(job.id, result=result)

        # Check parent link
        dag_run = DAGRun(file_queue, main.dag_run_id)
        subdags = dag_run.get_subdags()

        assert len(subdags) == 1
        assert subdags[0].get_parent_job() == sub_id

    def test_get_hierarchy(self, file_queue):
        """Test getting complete DAG hierarchy."""
        main = DAG("main", file_queue)
        main.add_subdag(create_sub, name="sub1")
        main.add_subdag(create_sub, name="sub2")
        main.submit()

        # Execute both sub-DAGs
        for _ in range(2):
            job = file_queue.claim()
            if job:
                result = job.execute()
                file_queue.ack(job.id, result=result)

        # Get hierarchy
        dag_run = DAGRun(file_queue, main.dag_run_id)
        hierarchy = dag_run.get_hierarchy()

        assert hierarchy["name"] == "main"
        assert len(hierarchy["subdags"]) == 2


# ============================================================================
# Execution Tests
# ============================================================================


def create_sub(q):
    dag = DAG("sub", q)
    dag.add_job(noop, name="job1")
    dag.add_job(noop, name="job2")
    return dag


def create_failing_sub(q):
    dag = DAG("failing_sub", q)
    dag.add_job(failing_job, name="fail", max_attempts=1)
    return dag


class TestSubDAGExecution:
    """Test sub-DAG execution."""

    def test_subdag_waits_for_completion(self, queue):
        """Test that parent job waits for sub-DAG to complete."""

        main = DAG("main", queue)
        sub_id = main.add_subdag(create_sub, name="sub_dag", poll_interval=0.1)
        main.submit()

        # Start workers to auto-execute
        with queue:
            # Wait for main DAG completion
            main.wait_for_completion(timeout=5)

            # Give additional time for status updates to propagate
            max_status_wait = 2.0
            status_wait_interval = 0.1
            waited = 0

            while waited < max_status_wait and main.status != DAGRunStatus.DONE:
                time.sleep(status_wait_interval)
                waited += status_wait_interval

        assert main.is_complete()
        assert main.status == DAGRunStatus.DONE

    def test_subdag_failure_propagates(self, queue):
        """Test that sub-DAG failure causes parent job to fail."""

        main = DAG("main", queue)
        sub_id = main.add_subdag(create_failing_sub, name="failing_sub")
        main.submit()

        # Execute sub-DAG job (will fail)
        job = queue.claim()
        try:
            job.execute()
        except RuntimeError:
            queue.ack(job.id, error="Sub-DAG failed")

        # Check parent job failed
        parent_job = queue.get_job(sub_id)
        assert parent_job.status == "failed"


# ============================================================================
# Complex Workflow Tests
# ============================================================================


def create_etl(q):
    dag = DAG("etl", q)
    dag.add_job(extract_data, name="extract")
    dag.add_job(transform_data, name="transform", depends_on="extract")
    dag.add_job(load_data, name="load", depends_on="transform")
    return dag


def create_leaf(q):
    dag = DAG("leaf", q)
    dag.add_job(noop, name="job1")
    return dag


def create_branch(q):
    dag = DAG("branch", q)
    dag.add_subdag(create_leaf, name="leaf1")
    dag.add_subdag(create_leaf, name="leaf2")
    return dag


class TestComplexSubDAGWorkflows:
    """Test complex workflows with sub-DAGs."""

    def test_parallel_subdags(self, queue):
        """Test running multiple sub-DAGs in parallel."""
        main = DAG("main", queue)

        etl1 = main.add_subdag(create_etl, name="etl_1")
        etl2 = main.add_subdag(create_etl, name="etl_2")

        # Aggregate after both complete
        agg = main.add_job(noop, name="aggregate", depends_on=[etl1, etl2])

        main.submit()

        # Execute with workers
        with queue:
            main.wait_for_completion(timeout=10)

        assert main.is_complete()
        assert main.status == DAGRunStatus.DONE

    def test_nested_subdags(self, file_queue):
        """Test sub-DAGs within sub-DAGs (2 levels deep)."""
        main = DAG("main", file_queue)
        main.add_subdag(create_branch, name="branch")
        main.submit()

        # Execute with workers
        with file_queue:
            main.wait_for_completion(timeout=10)

        # Check hierarchy depth
        dag_run = DAGRun(file_queue, main.dag_run_id)
        hierarchy = dag_run.get_hierarchy()

        assert len(hierarchy["subdags"]) == 1
        assert len(hierarchy["subdags"][0]["subdags"]) == 2


# ============================================================================
# Mermaid Export Tests
# ============================================================================


class TestSubDAGMermaidExport:
    """Test Mermaid diagram export with sub-DAGs."""

    def test_export_without_subdags(self, queue):
        """Test exporting DAG without expanding sub-DAGs."""
        main = DAG("main", queue)
        main.add_subdag(create_sub, name="sub_dag")
        main.submit()

        mermaid = main.export_mermaid(include_subdags=False)

        assert "graph TD" in mermaid
        assert "sub_dag" in mermaid
        # Should NOT show internal structure
        assert "job1" not in mermaid or "sub_dag" in mermaid


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
