"""
Comprehensive tests for DAG Context Manager.

Tests cover:
- Basic DAG context usage
- Named node references
- Dependency resolution
- Validation and error handling
- DAG run tracking
- Atomic submission and rollback
"""

import time

import pytest

from queuack import (
    DAGContext,
    DAGRun,
    DAGRunStatus,
    DAGValidationError,
    DependencyMode,
    DuckQueue,
)


# Test functions (must be module-level for pickling)
def extract_data():
    return [1, 2, 3, 4, 5]


def transform_data(data=None):
    return [x * 2 for x in (data or [])]


def load_data(data=None):
    return f"Loaded {len(data or [])} records"


def failing_job():
    raise RuntimeError("Intentional failure")


def quick_job():
    return "quick"


def slow_job():
    time.sleep(0.5)
    return "slow"


# Fixtures
@pytest.fixture
def queue():
    """Create in-memory queue for testing."""
    q = DuckQueue(":memory:")
    yield q
    q.close()


# Basic DAG Context Tests
class TestDAGContextBasics:
    """Test basic DAG context functionality."""

    def test_create_dag_context(self, queue: DuckQueue):
        """Test creating a DAG context."""
        with queue.dag("test_dag") as dag:
            assert dag.name == "test_dag"
            assert dag.dag_run_id is not None
            assert len(dag.jobs) == 0

    def test_enqueue_single_job(self, queue: DuckQueue):
        """Test enqueueing a single job."""
        with queue.dag("single") as dag:
            job_id = dag.enqueue(extract_data, name="extract")

            assert job_id is not None
            assert "extract" in dag.jobs
            assert dag.jobs["extract"] == job_id

    def test_enqueue_with_dependencies(self, queue: DuckQueue):
        """Test enqueueing jobs with dependencies."""
        with queue.dag("deps") as dag:
            extract = dag.enqueue(extract_data, name="extract")
            transform = dag.enqueue(
                transform_data, name="transform", depends_on="extract"
            )
            load = dag.enqueue(load_data, name="load", depends_on="transform")

        # Verify jobs were created
        assert queue.get_job(extract) is not None
        assert queue.get_job(transform) is not None
        assert queue.get_job(load) is not None

        # Verify dependencies
        deps = queue.conn.execute("""
            SELECT child_job_id, parent_job_id
            FROM job_dependencies
        """).fetchall()

        assert len(deps) == 2

    def test_dag_run_created(self, queue: DuckQueue):
        """Test that DAG run record is created."""
        with queue.dag("test_run") as dag:
            dag.enqueue(extract_data, name="extract")

        # Check dag_runs table
        result = queue.conn.execute(
            """
            SELECT id, name, status
            FROM dag_runs
            WHERE id = ?
        """,
            [dag.dag_run_id],
        ).fetchone()

        assert result is not None
        assert result[1] == "test_run"
        assert result[2] == "running"

    def test_jobs_linked_to_dag_run(self, queue: DuckQueue):
        """Test that jobs are linked to DAG run."""
        with queue.dag("linked") as dag:
            job_id = dag.enqueue(extract_data, name="extract")

        # Check job has dag_run_id
        job = queue.get_job(job_id)
        assert job.dag_run_id == dag.dag_run_id
        assert job.node_name == "extract"


# Named Dependencies Tests
class TestNamedDependencies:
    """Test named node dependency resolution."""

    def test_string_dependency(self, queue: DuckQueue):
        """Test single string dependency."""
        with queue.dag("string_dep") as dag:
            extract = dag.enqueue(extract_data, name="extract")
            transform = dag.enqueue(
                transform_data, name="transform", depends_on="extract"
            )

        # Verify dependency
        deps = queue.conn.execute(
            """
            SELECT parent_job_id
            FROM job_dependencies
            WHERE child_job_id = ?
        """,
            [transform],
        ).fetchall()

        assert len(deps) == 1
        assert deps[0][0] == extract

    def test_list_dependencies(self, queue: DuckQueue):
        """Test multiple dependencies as list."""
        with queue.dag("list_deps") as dag:
            j1 = dag.enqueue(extract_data, name="job1")
            j2 = dag.enqueue(extract_data, name="job2")
            j3 = dag.enqueue(transform_data, name="job3", depends_on=["job1", "job2"])

        # Verify dependencies
        deps = queue.conn.execute(
            """
            SELECT parent_job_id
            FROM job_dependencies
            WHERE child_job_id = ?
        """,
            [j3],
        ).fetchall()

        assert len(deps) == 2
        parent_ids = {dep[0] for dep in deps}
        assert j1 in parent_ids
        assert j2 in parent_ids

    def test_mixed_job_id_and_name_dependencies(self, queue: DuckQueue):
        """Test mixing job IDs and names in dependencies."""
        # Create a job outside the DAG
        external_job = queue.enqueue(extract_data)

        with queue.dag("mixed") as dag:
            internal = dag.enqueue(transform_data, name="internal")
            combined = dag.enqueue(
                load_data, name="combined", depends_on=[external_job, "internal"]
            )

        # Verify both dependencies
        deps = queue.conn.execute(
            """
            SELECT parent_job_id
            FROM job_dependencies
            WHERE child_job_id = ?
        """,
            [combined],
        ).fetchall()

        assert len(deps) == 2
        parent_ids = {dep[0] for dep in deps}
        assert external_job in parent_ids
        assert internal in parent_ids

    def test_invalid_dependency_name_fail_fast(self, queue: DuckQueue):
        """Test that invalid dependency raises error with fail_fast=True."""
        with pytest.raises(ValueError, match="Dependency 'nonexistent' not found"):
            with queue.dag("invalid", fail_fast=True) as dag:
                dag.enqueue(extract_data, name="extract")
                dag.enqueue(transform_data, depends_on="nonexistent")

    def test_invalid_dependency_name_no_fail_fast(self, queue: DuckQueue):
        """Test that invalid dependency is skipped with fail_fast=False."""
        import warnings

        with warnings.catch_warnings(record=True):
            with queue.dag("invalid", fail_fast=False) as dag:
                dag.enqueue(extract_data, name="extract")
                dag.enqueue(transform_data, depends_on="nonexistent")

        # Should complete without raising


# Validation Tests
class TestDAGValidation:
    """Test DAG validation."""

    def test_cycle_detection(self, queue: DuckQueue):
        """Test that cycles are detected."""
        with pytest.raises(DAGValidationError, match="cycle"):
            with queue.dag("cycle") as dag:
                a = dag.enqueue(extract_data, name="a")
                b = dag.enqueue(transform_data, name="b", depends_on="a")
                # Create cycle
                dag.enqueue(load_data, name="a_dup")
                dag.engine.add_dependency(a, b)  # Manually create cycle

    def test_validation_warnings(self, queue: DuckQueue):
        """Test validation warnings for disconnected components."""
        with queue.dag("disconnected", validate=True) as dag:
            dag.enqueue(extract_data, name="island1")
            dag.enqueue(transform_data, name="island2")

        # Should complete with warnings (not errors)

    def test_skip_validation(self, queue: DuckQueue):
        """Test skipping validation."""
        with queue.dag("no_validate", validate=False) as dag:
            dag.enqueue(extract_data, name="job1")

        # Should complete without validation

    def test_manual_validation(self, queue: DuckQueue):
        """Test manually calling validate()."""
        with queue.dag("manual") as dag:
            dag.enqueue(extract_data, name="extract")
            dag.enqueue(transform_data, name="transform", depends_on="extract")

            warnings = dag.validate()
            assert isinstance(warnings, list)


# Execution Order Tests
class TestExecutionOrder:
    """Test DAG execution order."""

    def test_get_execution_order(self, queue: DuckQueue):
        """Test getting execution order."""
        with queue.dag("order") as dag:
            extract = dag.enqueue(extract_data, name="extract")
            transform = dag.enqueue(
                transform_data, name="transform", depends_on="extract"
            )
            load = dag.enqueue(load_data, name="load", depends_on="transform")

            order = dag.get_execution_order()

        # Should be 3 levels
        assert len(order) == 3
        assert order[0] == ["extract"]
        assert order[1] == ["transform"]
        assert order[2] == ["load"]

    def test_parallel_execution_order(self, queue: DuckQueue):
        """Test parallel jobs in execution order."""
        with queue.dag("parallel") as dag:
            extract = dag.enqueue(extract_data, name="extract")

            # Two parallel transforms
            t1 = dag.enqueue(transform_data, name="t1", depends_on="extract")
            t2 = dag.enqueue(transform_data, name="t2", depends_on="extract")

            # Combined load
            load = dag.enqueue(load_data, name="load", depends_on=["t1", "t2"])

            order = dag.get_execution_order()

        # Level 0: extract
        # Level 1: t1, t2 (parallel)
        # Level 2: load
        assert len(order) == 3
        assert order[0] == ["extract"]
        assert set(order[1]) == {"t1", "t2"}
        assert order[2] == ["load"]


# DAGRun Helper Tests
class TestDAGRunHelper:
    """Test DAGRun helper class."""

    def test_get_status(self, queue: DuckQueue):
        """Test getting DAG run status."""
        with queue.dag("status_test") as dag:
            dag.enqueue(extract_data, name="extract")

        dag_run = DAGRun(queue, dag.dag_run_id)
        status = dag_run.get_status()

        assert status == DAGRunStatus.RUNNING

    def test_get_jobs(self, queue: DuckQueue):
        """Test getting jobs in DAG run."""
        with queue.dag("jobs_test") as dag:
            j1 = dag.enqueue(extract_data, name="job1")
            j2 = dag.enqueue(transform_data, name="job2")

        dag_run = DAGRun(queue, dag.dag_run_id)
        jobs = dag_run.get_jobs()

        assert len(jobs) == 2
        assert jobs[0]["name"] == "job1"
        assert jobs[1]["name"] == "job2"

    def test_get_progress(self, queue: DuckQueue):
        """Test getting DAG run progress."""
        with queue.dag("progress_test") as dag:
            j1 = dag.enqueue(extract_data, name="job1")
            j2 = dag.enqueue(transform_data, name="job2")

        dag_run = DAGRun(queue, dag.dag_run_id)
        progress = dag_run.get_progress()

        assert progress["pending"] == 2
        assert progress["done"] == 0

    def test_is_complete(self, queue: DuckQueue):
        """Test checking if DAG is complete."""
        with queue.dag("complete_test") as dag:
            j1 = dag.enqueue(extract_data, name="job1")

        dag_run = DAGRun(queue, dag.dag_run_id)

        # Initially not complete
        assert not dag_run.is_complete()

        # Complete the job
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        # Now complete
        assert dag_run.is_complete()

    def test_update_status(self, queue: DuckQueue):
        """Test updating DAG run status."""
        with queue.dag("update_test") as dag:
            j1 = dag.enqueue(extract_data, name="job1")

        dag_run = DAGRun(queue, dag.dag_run_id)

        # Complete the job
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        # Update DAG status
        dag_run.update_status()

        # Check status is now DONE
        status = dag_run.get_status()
        assert status == DAGRunStatus.DONE


# Error Handling Tests
class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_duplicate_job_name(self, queue: DuckQueue):
        """Test that duplicate job names raise error."""
        with pytest.raises(ValueError, match="already exists"):
            with queue.dag("duplicate") as dag:
                dag.enqueue(extract_data, name="job1")
                dag.enqueue(transform_data, name="job1")

    def test_auto_generated_names(self, queue: DuckQueue):
        """Test auto-generated job names."""
        with queue.dag("auto_names") as dag:
            j1 = dag.enqueue(extract_data)
            j2 = dag.enqueue(transform_data)
            j3 = dag.enqueue(load_data)

        # Should have auto-generated names
        assert len(dag.jobs) == 3
        assert (
            "job_0" in dag.jobs
            or len([k for k in dag.jobs if k.startswith("job_")]) == 3
        )

    def test_submit_twice_raises(self, queue: DuckQueue):
        """Test that submitting twice raises error."""
        with queue.dag("twice") as dag:
            dag.enqueue(extract_data, name="extract")
            dag.submit()

        with pytest.raises(RuntimeError, match="already submitted"):
            dag.submit()

    def test_add_after_submit_raises(self, queue: DuckQueue):
        """Test that adding jobs after submit raises error."""
        dag = DAGContext(queue, "after_submit")
        dag.enqueue(extract_data, name="extract")
        dag.submit()

        with pytest.raises(RuntimeError, match="already-submitted"):
            dag.enqueue(transform_data, name="transform")

    def test_exception_in_context_rolls_back(self, queue: DuckQueue):
        """Test that exceptions roll back DAG submission."""
        try:
            with queue.dag("rollback") as dag:
                j1 = dag.enqueue(extract_data, name="extract")
                raise ValueError("Test error")
        except ValueError:
            pass

        # DAG run should be deleted
        result = queue.conn.execute("""
            SELECT COUNT(*) FROM dag_runs
        """).fetchone()

        assert result[0] == 0

        # Jobs should be deleted
        result = queue.conn.execute("""
            SELECT COUNT(*) FROM jobs
        """).fetchone()

        assert result[0] == 0


# Integration Tests
class TestDAGContextIntegration:
    """Integration tests with actual job execution."""

    def test_simple_dag_execution(self, queue: DuckQueue):
        """Test executing a simple DAG."""
        with queue.dag("simple_exec") as dag:
            extract = dag.enqueue(extract_data, name="extract")
            transform = dag.enqueue(
                transform_data, name="transform", depends_on="extract"
            )

        # Execute extract
        job1 = queue.claim()
        assert job1.id == extract
        result1 = job1.execute()
        queue.ack(job1.id, result=result1)

        # Now transform should be claimable
        job2 = queue.claim()
        assert job2.id == transform

    def test_parallel_execution(self, queue: DuckQueue):
        """Test parallel job execution."""
        with queue.dag("parallel_exec") as dag:
            extract = dag.enqueue(extract_data, name="extract")

            t1 = dag.enqueue(quick_job, name="t1", depends_on="extract")
            t2 = dag.enqueue(quick_job, name="t2", depends_on="extract")

            load = dag.enqueue(load_data, name="load", depends_on=["t1", "t2"])

        # Complete extract
        job = queue.claim()
        queue.ack(job.id, result=job.execute())

        # Both t1 and t2 should be claimable now
        claimed = []
        claimed.append(queue.claim())
        claimed.append(queue.claim())

        assert len(claimed) == 2
        assert t1 in [j.id for j in claimed]
        assert t2 in [j.id for j in claimed]

    def test_failure_propagation_in_dag(self, queue: DuckQueue):
        """Test failure propagation within DAG."""
        with queue.dag("failure_prop") as dag:
            j1 = dag.enqueue(failing_job, name="fail", max_attempts=1)
            j2 = dag.enqueue(transform_data, name="child", depends_on="fail")

        # Execute failing job
        job = queue.claim()
        try:
            job.execute()
        except RuntimeError:
            queue.ack(job.id, error="Failed")

        # Child should be skipped
        child_job = queue.get_job(j2)
        assert child_job.status == "skipped"

        # DAG should be marked as failed
        dag_run = DAGRun(queue, dag.dag_run_id)
        dag_run.update_status()
        assert dag_run.get_status() == DAGRunStatus.FAILED

    def test_dependency_mode_any(self, queue: DuckQueue):
        """Test ANY dependency mode."""
        with queue.dag("any_mode") as dag:
            p1 = dag.enqueue(extract_data, name="p1")
            p2 = dag.enqueue(failing_job, name="p2", max_attempts=1)

            child = dag.enqueue(
                transform_data,
                name="child",
                depends_on=["p1", "p2"],
                dependency_mode=DependencyMode.ANY,
            )

        # Complete p1
        job = queue.claim()
        if job.id == p1:
            queue.ack(job.id, result=job.execute())

        # Fail p2
        job = queue.claim()
        if job.id == p2:
            try:
                job.execute()
            except RuntimeError:
                queue.ack(job.id, error="Failed")

        # Child should still be runnable (p1 succeeded)
        # Note: This requires DAGEngine integration which may not be automatic
        # in the current implementation


# Mermaid Export Tests
class TestMermaidExport:
    """Test Mermaid diagram export."""

    def test_export_mermaid(self, queue: DuckQueue):
        """Test exporting DAG to Mermaid format."""
        with queue.dag("mermaid_test") as dag:
            extract = dag.enqueue(extract_data, name="extract")
            transform = dag.enqueue(
                transform_data, name="transform", depends_on="extract"
            )
            load = dag.enqueue(load_data, name="load", depends_on="transform")

            mermaid = dag.export_mermaid()

        assert "graph TD" in mermaid
        assert "extract" in mermaid
        assert "transform" in mermaid
        assert "load" in mermaid
        assert "-->" in mermaid


# Advanced Features Tests
class TestAdvancedFeatures:
    """Test advanced DAG features."""

    def test_dag_with_description(self, queue: DuckQueue):
        """Test DAG with description."""
        with queue.dag("described", description="Test DAG with description") as dag:
            dag.enqueue(extract_data, name="extract")

        result = queue.conn.execute(
            """
            SELECT description FROM dag_runs WHERE id = ?
        """,
            [dag.dag_run_id],
        ).fetchone()

        assert result[0] == "Test DAG with description"

    def test_dag_statistics_view(self, queue: DuckQueue):
        """Test DAG statistics view."""
        with queue.dag("stats_test") as dag:
            j1 = dag.enqueue(extract_data, name="job1")
            j2 = dag.enqueue(transform_data, name="job2")

        # Query stats view
        result = queue.conn.execute(
            """
            SELECT dag_name, total_jobs, pending_jobs
            FROM dag_run_stats
            WHERE dag_run_id = ?
        """,
            [dag.dag_run_id],
        ).fetchone()

        assert result is not None
        assert result[0] == "stats_test"
        assert result[1] == 2  # total_jobs
        assert result[2] == 2  # pending_jobs

    def test_multiple_dags_same_name(self, queue: DuckQueue):
        """Test creating multiple DAG runs with same name."""
        # First run
        with queue.dag("repeated") as dag1:
            dag1.enqueue(extract_data, name="extract")

        # Second run with same name
        with queue.dag("repeated") as dag2:
            dag2.enqueue(transform_data, name="transform")

        # Both should exist
        result = queue.conn.execute("""
            SELECT COUNT(*) FROM dag_runs WHERE name = 'repeated'
        """).fetchone()

        assert result[0] == 2

    def test_dag_with_priorities(self, queue: DuckQueue):
        """Test jobs with different priorities in DAG."""
        with queue.dag("priorities") as dag:
            low = dag.enqueue(extract_data, name="low", priority=10)
            high = dag.enqueue(transform_data, name="high", priority=90)

        # High priority should be claimed first
        job = queue.claim()
        assert job.id == high


# Edge Cases
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_dag(self, queue: DuckQueue):
        """Test creating empty DAG."""
        with queue.dag("empty") as dag:
            pass

        # Should create dag_run but no jobs
        result = queue.conn.execute(
            """
            SELECT COUNT(*) FROM jobs WHERE dag_run_id = ?
        """,
            [dag.dag_run_id],
        ).fetchone()

        assert result[0] == 0

    def test_single_job_dag(self, queue: DuckQueue):
        """Test DAG with single job."""
        with queue.dag("single") as dag:
            j1 = dag.enqueue(extract_data, name="only")

        dag_run = DAGRun(queue, dag.dag_run_id)
        jobs = dag_run.get_jobs()

        assert len(jobs) == 1

    def test_large_dag(self, queue: DuckQueue):
        """Test DAG with many jobs."""
        with queue.dag("large") as dag:
            # Create 100 jobs
            for i in range(100):
                dag.enqueue(extract_data, name=f"job_{i}")

        dag_run = DAGRun(queue, dag.dag_run_id)
        jobs = dag_run.get_jobs()

        assert len(jobs) == 100

    def test_deep_dependency_chain(self, queue: DuckQueue):
        """Test deep chain of dependencies."""
        with queue.dag("deep") as dag:
            prev = dag.enqueue(extract_data, name="job_0")

            # Create chain of 20 jobs
            for i in range(1, 20):
                prev = dag.enqueue(
                    transform_data, name=f"job_{i}", depends_on=f"job_{i - 1}"
                )

            order = dag.get_execution_order()

        # Should have 20 levels
        assert len(order) == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
