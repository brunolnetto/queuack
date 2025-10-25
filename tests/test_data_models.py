# file: test_data_models.py

import pickle
import time

import pytest

from queuack.core import DAG, DuckQueue
from queuack.data_models import (
    BackpressureError,
    Job,
    NodeKind,
    NodeType,
    TaskContext,
    get_context,
    set_context,
)
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


def factory_with_queue_param(queue):
    """First parameter named "queue" should be detected as SUBDAG."""
    return None


def factory_with_q_param(q):
    """Alias 'q' should also be detected as SUBDAG."""
    return None


def ordinary_job(x):
    """Ordinary job with a first positional parameter that's not queue-like."""
    return x


class FakeDuckQueue:
    """Dummy type used only for annotation testing."""


def factory_with_annotated_param(q: FakeDuckQueue):
    """Annotated first parameter referencing a DuckQueue-like type -> SUBDAG."""
    return None


def test_detect_by_param_name_queue():
    t = NodeType.detect(factory_with_queue_param)
    assert t.kind == NodeKind.SUBDAG


def test_detect_by_param_name_q():
    t = NodeType.detect(factory_with_q_param)
    assert t.kind == NodeKind.SUBDAG


def test_detect_by_annotation():
    t = NodeType.detect(factory_with_annotated_param)
    assert t.kind == NodeKind.SUBDAG


def test_detect_ordinary_function_is_job():
    t = NodeType.detect(ordinary_job)
    assert t.kind == NodeKind.JOB


def test_detect_builtin_is_job():
    # Builtins/C functions should be treated as JOBs (inspect may raise)
    t = NodeType.detect(len)
    assert t.kind == NodeKind.JOB


# Test helper functions (module-level for pickling)
def simple_task():
    """Task without context."""
    return {"value": 42}


def task_with_context(context):
    """Task that uses context."""
    return {"has_context": context is not None, "job_id": context.job_id}


def task_with_ctx(ctx):
    """Task using 'ctx' instead of 'context'."""
    return {"has_ctx": ctx is not None}


def upstream_task():
    """Parent task."""
    return {"data": [1, 2, 3, 4, 5]}


def downstream_task(context):
    """Child task that pulls parent result."""
    parent_data = context.upstream("upstream")
    return {"sum": sum(parent_data["data"])}


def multi_parent_task():
    """First parent."""
    return {"source": "parent1", "value": 10}


def multi_parent_task2():
    """Second parent."""
    return {"source": "parent2", "value": 20}


def combine_task(context):
    """Task with multiple parents."""
    parent1 = context.upstream("parent1")
    parent2 = context.upstream("parent2")
    return {"total": parent1["value"] + parent2["value"]}


def get_all_parents_task(context):
    """Task that gets all parent results."""
    parents = context.get_parent_results()
    return {"count": len(parents), "data": parents}


def helper_function_task(context):
    """Task that calls helper using get_context()."""
    return helper_that_uses_context()


def helper_that_uses_context():
    """Helper function that accesses context."""
    ctx = get_context()
    if ctx:
        return {"helper_has_context": True, "job_id": ctx.job_id}
    return {"helper_has_context": False}


def optional_upstream_task(context):
    """Task that checks for optional upstream."""
    if context.has_upstream("optional"):
        data = context.upstream("optional")
        return {"has_optional": True, "data": data}
    return {"has_optional": False}


def task_that_fails(context):
    """Task that raises exception."""
    raise ValueError("Intentional failure")


class TestBasicContext:
    """Test basic context functionality."""

    def test_context_creation(self):
        """Test creating a TaskContext."""
        ctx = TaskContext(
            job_id="test-job-123", queue_path=":memory:", dag_run_id="dag-run-456"
        )

        assert ctx.job_id == "test-job-123"
        assert ctx.queue_path == ":memory:"
        assert ctx.dag_run_id == "dag-run-456"

    def test_context_as_context_manager(self):
        """Test context manager protocol."""
        ctx = TaskContext(job_id="test-job", queue_path=":memory:")

        with ctx as c:
            assert c is ctx
            # Queue should be lazy-loaded
            assert ctx._queue is None

        # Should cleanup on exit
        # (queue is created on access, not tested here)

    def test_get_set_context(self):
        """Test thread-local context storage."""
        # Initially no context
        assert get_context() is None

        # Set context
        ctx = TaskContext(job_id="test", queue_path=":memory:")
        set_context(ctx)

        # Should retrieve same context
        assert get_context() is ctx

        # Clear context
        set_context(None)
        assert get_context() is None


class TestContextInjection:
    """Test automatic context injection during job execution."""

    def test_task_without_context_works(self):
        """Tasks without context parameter should work normally."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(simple_task)
        job = queue.claim()

        result = job.execute()
        queue.ack(job_id, result=result)

        assert result == {"value": 42}

        queue.close()

    def test_task_with_context_gets_injection(self):
        """Tasks with context parameter should receive it."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(task_with_context)
        job = queue.claim()

        result = job.execute()
        queue.ack(job_id, result=result)

        assert result["has_context"] is True
        assert result["job_id"] == job_id

        queue.close()

    def test_task_with_ctx_parameter(self):
        """Tasks using 'ctx' should also get injection."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(task_with_ctx)
        job = queue.claim()

        result = job.execute()
        queue.ack(job_id, result=result)

        assert result["has_ctx"] is True

        queue.close()


def bad_task(context):
    # Try to access upstream that doesn't exist
    return context.upstream("nonexistent")


def task_with_upstream_no_dag(context):
    # This should fail - not in a DAG
    return context.upstream("something")


class TestUpstreamAccess:
    """Test accessing upstream task results."""

    def test_upstream_by_name(self):
        """Test accessing parent by task name."""
        queue = DuckQueue(":memory:")

        with DAG("test_upstream", queue) as dag:
            dag.add_job(upstream_task, name="upstream")
            dag.add_job(downstream_task, name="downstream", depends_on="upstream")

        # Wait for completion
        run_id = dag.dag_run_id
        while not dag.is_complete():
            job = queue.claim()
            if job:
                result = job.execute()
                queue.ack(job.id, result=result)
            else:
                time.sleep(0.01)

        # Check downstream result
        downstream_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'downstream' AND dag_run_id = ?
        """,
            [run_id],
        ).fetchone()

        result = queue.get_result(downstream_job[0])
        assert result == {"sum": 15}  # sum([1,2,3,4,5])

        queue.close()

    def test_multiple_parents(self):
        """Test task with multiple parent dependencies."""
        queue = DuckQueue(":memory:")

        with DAG("test_multi_parent", queue) as dag:
            dag.add_job(multi_parent_task, name="parent1")
            dag.add_job(multi_parent_task2, name="parent2")
            dag.add_job(combine_task, name="combine", depends_on=["parent1", "parent2"])

        # Execute all jobs
        while not dag.is_complete():
            job = queue.claim()
            if job:
                result = job.execute()
                queue.ack(job.id, result=result)
            else:
                time.sleep(0.01)

        # Check combined result
        combine_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'combine'
        """,
            [],
        ).fetchone()

        result = queue.get_result(combine_job[0])
        assert result == {"total": 30}  # 10 + 20

        queue.close()

    def test_get_all_parents(self):
        """Test getting all parent results at once."""
        queue = DuckQueue(":memory:")

        with DAG("test_get_all", queue) as dag:
            dag.add_job(multi_parent_task, name="p1")
            dag.add_job(multi_parent_task2, name="p2")
            dag.add_job(get_all_parents_task, name="child", depends_on=["p1", "p2"])

        # Execute
        while not dag.is_complete():
            job = queue.claim()
            if job:
                result = job.execute()
                queue.ack(job.id, result=result)
            else:
                time.sleep(0.01)

        # Check result
        child_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'child'
        """,
            [],
        ).fetchone()

        result = queue.get_result(child_job[0])
        assert result["count"] == 2
        assert len(result["data"]) == 2

        queue.close()

    def test_upstream_not_found_raises(self):
        """Test that accessing non-existent upstream raises."""
        queue = DuckQueue(":memory:")

        with DAG("test_bad_upstream", queue) as dag:
            dag.add_job(upstream_task, name="upstream")
            dag.add_job(bad_task, name="bad", depends_on="upstream")

        # Execute upstream
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        # Execute bad task - should fail
        job = queue.claim()
        with pytest.raises(ValueError, match="No upstream task named 'nonexistent'"):
            job.execute()

        queue.close()

    def test_upstream_without_dag_raises(self):
        """Test that upstream() requires DAG context."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(task_with_upstream_no_dag)
        job = queue.claim()

        with pytest.raises(ValueError, match="requires DAG context"):
            job.execute()

        queue.close()


class TestHelperFunctions:
    """Test context access from helper functions."""

    def test_helper_function_gets_context(self):
        """Helper functions can access context via get_context()."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(helper_function_task)
        job = queue.claim()

        result = job.execute()
        queue.ack(job_id, result=result)

        assert result["helper_has_context"] is True
        assert result["job_id"] == job_id

        queue.close()


class TestOptionalUpstream:
    """Test conditional upstream access."""

    def test_has_upstream_true(self):
        """Test has_upstream() returns True when parent exists."""
        queue = DuckQueue(":memory:")

        with DAG("test_optional", queue) as dag:
            dag.add_job(upstream_task, name="optional")
            dag.add_job(optional_upstream_task, name="child", depends_on="optional")

        # Execute
        while not dag.is_complete():
            job = queue.claim()
            if job:
                result = job.execute()
                queue.ack(job.id, result=result)
            else:
                time.sleep(0.01)

        # Check result
        child_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'child'
        """,
            [],
        ).fetchone()

        result = queue.get_result(child_job[0])
        assert result["has_optional"] is True
        assert "data" in result

        queue.close()

    def test_has_upstream_false(self):
        """Test has_upstream() returns False when parent doesn't exist."""
        queue = DuckQueue(":memory:")

        with DAG("test_no_optional", queue) as dag:
            # No "optional" parent this time
            dag.add_job(optional_upstream_task, name="child")

        # Execute
        job = queue.claim()
        result = job.execute()
        queue.ack(job.id, result=result)

        assert result["has_optional"] is False

        queue.close()


def check_parents(context):
    names = context.get_parent_names()
    return {"parent_names": sorted(names)}


class TestContextCleanup:
    """Test context cleanup and resource management."""

    def test_context_cleanup_on_success(self):
        """Context should cleanup even on successful execution."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(task_with_context)
        job = queue.claim()

        # Before execution, no context
        assert get_context() is None

        result = job.execute()

        # After execution, context should be cleaned up
        assert get_context() is None

        queue.ack(job_id, result=result)
        queue.close()

    def test_context_cleanup_on_failure(self):
        """Context should cleanup even if task fails."""
        queue = DuckQueue(":memory:")

        job_id = queue.enqueue(task_that_fails)
        job = queue.claim()

        # Before execution, no context
        assert get_context() is None

        with pytest.raises(ValueError, match="Intentional failure"):
            job.execute()

        # After execution, context should be cleaned up even on error
        assert get_context() is None

        queue.close()


class TestGetParentNames:
    """Test retrieving parent task names."""

    def test_get_parent_names(self):
        """Test getting list of parent names."""
        queue = DuckQueue(":memory:")

        with DAG("test_parent_names", queue) as dag:
            dag.add_job(multi_parent_task, name="parent1")
            dag.add_job(multi_parent_task2, name="parent2")
            dag.add_job(check_parents, name="child", depends_on=["parent1", "parent2"])

        # Execute
        while not dag.is_complete():
            job = queue.claim()
            if job:
                result = job.execute()
                queue.ack(job.id, result=result)
            else:
                time.sleep(0.01)

        # Check result
        child_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'child'
        """,
            [],
        ).fetchone()

        result = queue.get_result(child_job[0])
        assert result["parent_names"] == ["parent1", "parent2"]

        queue.close()


class TestContextWithWorkers:
    """Test context injection with background workers."""

    def test_context_with_worker_pool(self):
        """Context should work with background workers."""
        queue = DuckQueue(":memory:", workers_num=2)

        with queue:
            with DAG("test_workers", queue) as dag:
                dag.add_job(upstream_task, name="upstream")
                dag.add_job(downstream_task, name="downstream", depends_on="upstream")

            # Wait for completion
            dag.wait_for_completion(timeout=5.0)

        # Verify results
        downstream_job = queue.conn.execute(
            """
            SELECT id FROM jobs WHERE node_name = 'downstream'
        """,
            [],
        ).fetchone()

        result = queue.get_result(downstream_job[0])
        assert result == {"sum": 15}


# ============================================================================
# Pattern 1: Context Only
# ============================================================================


def context_only(context):
    """Most common pattern - context as only parameter."""
    return {"pattern": "context_only", "job_id": context.job_id, "has_context": True}


# ============================================================================
# Pattern 2: Args + Context
# ============================================================================


def args_then_context(arg1, arg2, context):
    """Regular args followed by context."""
    return {
        "pattern": "args_then_context",
        "arg1": arg1,
        "arg2": arg2,
        "job_id": context.job_id,
    }


# ============================================================================
# Pattern 3: Context + Kwargs
# ============================================================================


def context_with_kwargs(context, multiplier=2, prefix="result"):
    """Context with optional kwargs."""
    return {
        "pattern": "context_with_kwargs",
        "job_id": context.job_id,
        "multiplier": multiplier,
        "prefix": prefix,
    }


# ============================================================================
# Pattern 4: Args + Context + Kwargs
# ============================================================================


def args_context_kwargs(arg1, context, multiplier=2):
    """All three: positional args, context, and kwargs."""
    return {
        "pattern": "args_context_kwargs",
        "arg1": arg1,
        "job_id": context.job_id,
        "multiplier": multiplier,
    }


# ============================================================================
# Pattern 5: Context with ctx alias
# ============================================================================


def using_ctx_alias(ctx):
    """Using 'ctx' instead of 'context'."""
    return {"pattern": "using_ctx", "job_id": ctx.job_id}


# ============================================================================
# Pattern 6: No Context (Backward Compatibility)
# ============================================================================


def no_context(arg1, arg2):
    """Old-style task without context."""
    return {"pattern": "no_context", "arg1": arg1, "arg2": arg2}


# ============================================================================
# Pattern 7: Upstream Access
# ============================================================================


def parent_task():
    """Parent task that returns data."""
    return {"data": [1, 2, 3, 4, 5]}


def child_with_upstream(context):
    """Child that accesses parent via context."""
    parent_data = context.upstream("parent")
    return {
        "pattern": "upstream_access",
        "parent_data": parent_data,
        "sum": sum(parent_data["data"]),
    }


# ============================================================================
# Test Runner
# ============================================================================


def test_pattern_1():
    """Test: Context only."""
    print("\n📝 Pattern 1: Context Only")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(context_only)

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "context_only"
    assert result["has_context"] is True

    queue.close()
    print("✅ Pattern 1 passed!")


def test_pattern_2():
    """Test: Args + Context."""
    print("\n📝 Pattern 2: Args + Context")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(args_then_context, args=("hello", "world"))

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "args_then_context"
    assert result["arg1"] == "hello"
    assert result["arg2"] == "world"

    queue.close()
    print("✅ Pattern 2 passed!")


def test_pattern_3():
    """Test: Context + Kwargs."""
    print("\n📝 Pattern 3: Context + Kwargs")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(
        context_with_kwargs, kwargs={"multiplier": 5, "prefix": "test"}
    )

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "context_with_kwargs"
    assert result["multiplier"] == 5
    assert result["prefix"] == "test"

    queue.close()
    print("✅ Pattern 3 passed!")


def test_pattern_4():
    """Test: Args + Context + Kwargs."""
    print("\n📝 Pattern 4: Args + Context + Kwargs")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(
        args_context_kwargs, args=("value1",), kwargs={"multiplier": 10}
    )

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "args_context_kwargs"
    assert result["arg1"] == "value1"
    assert result["multiplier"] == 10

    queue.close()
    print("✅ Pattern 4 passed!")


def test_pattern_5():
    """Test: Using ctx alias."""
    print("\n📝 Pattern 5: ctx Alias")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(using_ctx_alias)

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "using_ctx"

    queue.close()
    print("✅ Pattern 5 passed!")


def test_pattern_6():
    """Test: No context (backward compatibility)."""
    print("\n📝 Pattern 6: No Context (Backward Compat)")
    print("-" * 50)

    queue = DuckQueue(":memory:")
    job_id = queue.enqueue(no_context, args=("arg1", "arg2"))

    job = queue.claim()
    result = job.execute()
    queue.ack(job_id, result=result)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "no_context"
    assert result["arg1"] == "arg1"
    assert result["arg2"] == "arg2"

    queue.close()
    print("✅ Pattern 6 passed!")


def test_pattern_7():
    """Test: Upstream access in DAG."""
    print("\n📝 Pattern 7: Upstream Access")
    print("-" * 50)

    queue = DuckQueue(":memory:")

    with DAG("test_upstream", queue) as dag:
        dag.add_job(parent_task, name="parent")
        dag.add_job(child_with_upstream, name="child", depends_on="parent")

    # Execute
    import time

    while not dag.is_complete():
        job = queue.claim()
        if job:
            result = job.execute()
            queue.ack(job.id, result=result)
        else:
            time.sleep(0.01)

    # Get child result
    child_job_id = dag.jobs["child"]
    result = queue.get_result(child_job_id)

    print(f"✅ Result: {result}")
    assert result["pattern"] == "upstream_access"
    assert result["sum"] == 15  # sum([1,2,3,4,5])

    queue.close()
    print("✅ Pattern 7 passed!")
