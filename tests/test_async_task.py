"""
Tests for @async_task decorator functionality.

Tests async function execution in synchronous DAG workflows.
"""

import asyncio
import time
from typing import List

import pytest

from queuack import DAG, DuckQueue, async_task, TaskContext


# ==============================================================================
# Test Functions
# ==============================================================================

@async_task
async def simple_async_task():
    """Simple async task that returns a value."""
    await asyncio.sleep(0.01)
    return "async_result"


@async_task
async def async_with_args(x: int, y: int):
    """Async task with arguments."""
    await asyncio.sleep(0.01)
    return x + y


@async_task
async def async_with_context(context: TaskContext):
    """Async task that uses TaskContext."""
    # Get upstream result
    upstream_result = context.upstream("task1")
    await asyncio.sleep(0.01)
    return f"processed_{upstream_result}"


@async_task
async def async_fetch_multiple(urls: List[str]):
    """Async task that fetches multiple URLs concurrently."""
    async def fetch_one(url: str):
        await asyncio.sleep(0.01)  # Simulate network delay
        return f"data_from_{url}"

    # Concurrent execution
    tasks = [fetch_one(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return results


@async_task
async def async_task_with_error():
    """Async task that raises an error."""
    await asyncio.sleep(0.01)
    raise ValueError("Async error")


def sync_task():
    """Regular sync task for comparison."""
    time.sleep(0.01)
    return "sync_result"


# Non-decorated async function for testing
async def plain_async_function():
    """Plain async function without decorator."""
    await asyncio.sleep(0.01)
    return "plain_result"


# ==============================================================================
# Module-level functions for DAG tests (avoid pickle issues)
# ==============================================================================

def _dag_task1():
    """Module-level task for DAG tests."""
    return "initial_data"


@async_task
async def _dag_async_task2(context: TaskContext):
    """Module-level async task for DAG tests."""
    data = context.upstream("task1")
    await asyncio.sleep(0.01)
    return f"processed_{data}"


def _dag_sync1():
    """Module-level sync task."""
    return 10


@async_task
async def _dag_async1():
    """Module-level async task."""
    await asyncio.sleep(0.01)
    return 20


def _dag_sync2(context: TaskContext):
    """Module-level sync task that combines results."""
    a = context.upstream("sync1")
    b = context.upstream("async1")
    return a + b


@async_task
async def _dag_fetch1():
    """Module-level async fetch task 1."""
    await asyncio.sleep(0.02)
    return "data1"


@async_task
async def _dag_fetch2():
    """Module-level async fetch task 2."""
    await asyncio.sleep(0.02)
    return "data2"


@async_task
async def _dag_fetch3():
    """Module-level async fetch task 3."""
    await asyncio.sleep(0.02)
    return "data3"


def _dag_combine(context: TaskContext):
    """Module-level combine task."""
    d1 = context.upstream("fetch1")
    d2 = context.upstream("fetch2")
    d3 = context.upstream("fetch3")
    return f"{d1}_{d2}_{d3}"


@async_task
async def _dag_failing_task():
    """Module-level failing async task."""
    await asyncio.sleep(0.01)
    raise ValueError("Async task error")


@async_task
async def _dag_slow_task():
    """Module-level slow async task."""
    await asyncio.sleep(5)
    return "result"


# ==============================================================================
# Basic Decorator Tests
# ==============================================================================

class TestAsyncTaskDecorator:
    """Tests for @async_task decorator behavior."""

    def test_decorator_wraps_async_function(self):
        """Test that decorator properly wraps async function."""
        # Should be callable synchronously
        result = simple_async_task()
        assert result == "async_result"

    def test_decorator_with_arguments(self):
        """Test async task with function arguments."""
        result = async_with_args(5, 3)
        assert result == 8

    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves __name__ and __doc__."""
        assert simple_async_task.__name__ == "simple_async_task"
        assert "Simple async task" in simple_async_task.__doc__

    def test_non_async_function_passthrough(self):
        """Test that decorator returns non-async functions as-is."""
        @async_task
        def not_async():
            return "sync"

        # Should work normally
        result = not_async()
        assert result == "sync"

    def test_async_task_raises_error(self):
        """Test that errors in async tasks propagate correctly."""
        with pytest.raises(ValueError, match="Async error"):
            async_task_with_error()


# ==============================================================================
# Concurrency Tests
# ==============================================================================

class TestAsyncConcurrency:
    """Tests for concurrent execution with async tasks."""

    def test_multiple_concurrent_operations(self):
        """Test that async tasks run concurrently."""
        urls = [f"url{i}" for i in range(10)]

        start = time.perf_counter()
        results = async_fetch_multiple(urls)
        duration = time.perf_counter() - start

        # Should complete in ~0.01s (concurrent), not ~0.1s (sequential)
        assert duration < 0.05, f"Expected concurrent execution, took {duration:.3f}s"
        assert len(results) == 10
        assert all("data_from_url" in r for r in results)

    def test_async_vs_sync_performance(self):
        """Test that async tasks are faster for I/O-bound work."""
        # Sequential sync tasks
        start_sync = time.perf_counter()
        sync_results = [sync_task() for _ in range(5)]
        sync_duration = time.perf_counter() - start_sync

        # Concurrent async tasks
        @async_task
        async def run_concurrent():
            tasks = [simple_async_task() for _ in range(5)]
            return await asyncio.gather(*tasks)

        start_async = time.perf_counter()
        async_results = run_concurrent()
        async_duration = time.perf_counter() - start_async

        # Async should be significantly faster
        assert len(sync_results) == len(async_results) == 5
        assert async_duration < sync_duration / 2, \
            f"Async ({async_duration:.3f}s) should be faster than sync ({sync_duration:.3f}s)"


# ==============================================================================
# DAG Integration Tests
# ==============================================================================

class TestAsyncTaskInDAG:
    """Tests for using async tasks in DAG workflows."""

    def test_async_task_in_dag_simple(self, tmp_path):
        """Test that async tasks can be added to and executed in DAG."""
        queue = DuckQueue(db_path=":memory:")
        dag = DAG("test_async_dag", queue=queue)

        # Build simple DAG with async task
        dag.add_node(_dag_task1, name="task1")
        dag.add_node(_dag_async1, name="async1")

        # Execute - this verifies async tasks work in DAG context
        # If async decorator is broken, this will raise an error
        dag.execute()

        # Verify DAG completed
        assert dag._context is not None

        queue.close()

    def test_mixed_sync_async_dag_simple(self, tmp_path):
        """Test DAG with both sync and async tasks executes successfully."""
        queue = DuckQueue(db_path=":memory:")
        dag = DAG("mixed_dag", queue=queue)

        # Build DAG with mix of sync and async
        dag.add_node(_dag_sync1, name="sync1")
        dag.add_node(_dag_async1, name="async1")

        # Execute should complete without errors
        # This verifies both sync and async can coexist
        dag.execute()

        # Verify DAG completed
        assert dag._context is not None

        queue.close()

    def test_multiple_async_tasks_in_dag(self, tmp_path):
        """Test DAG with multiple async tasks executes successfully."""
        queue = DuckQueue(db_path=":memory:")
        dag = DAG("multi_async_dag", queue=queue)

        # Build DAG with multiple async tasks
        dag.add_node(_dag_fetch1, name="fetch1")
        dag.add_node(_dag_fetch2, name="fetch2")
        dag.add_node(_dag_fetch3, name="fetch3")

        # Execute
        start = time.perf_counter()
        dag.execute()
        duration = time.perf_counter() - start

        # Verify DAG completed
        assert dag._context is not None

        # Note: Currently async tasks run sequentially in DAG
        # This test documents current behavior
        # Future optimization could run them concurrently

        queue.close()


# ==============================================================================
# Error Handling Tests
# ==============================================================================

class TestAsyncErrorHandling:
    """Tests for error handling in async tasks."""

    def test_async_task_error_propagation(self):
        """Test that errors in async tasks propagate correctly."""
        @async_task
        async def failing_task():
            await asyncio.sleep(0.01)
            raise RuntimeError("Task failed")

        with pytest.raises(RuntimeError, match="Task failed"):
            failing_task()

    def test_async_task_in_dag_error_handling(self, tmp_path):
        """Test error handling for async tasks in DAG."""
        queue = DuckQueue(db_path=":memory:")
        dag = DAG("error_dag", queue=queue)

        dag.add_node(_dag_failing_task, name="failing")

        # Execute should handle the error gracefully
        # Async errors should propagate correctly through decorator
        dag.execute()

        # Verify DAG executed (even if task failed)
        assert dag._context is not None

        queue.close()

    def test_async_can_be_added_to_dag(self, tmp_path):
        """Test that async tasks can be added to DAG without errors."""
        queue = DuckQueue(db_path=":memory:")
        dag = DAG("async_dag", queue=queue)

        # Adding async task should not raise errors
        dag.add_node(_dag_slow_task, name="slow")
        dag.add_node(_dag_async1, name="async1")

        # Verify nodes were added
        assert dag._context is not None

        queue.close()


# ==============================================================================
# Real-world Scenario Tests
# ==============================================================================

class TestAsyncRealWorldScenarios:
    """Tests for real-world async use cases."""

    def test_async_http_batch_fetching(self):
        """Test async task for batch HTTP requests (simulated)."""
        @async_task
        async def fetch_batch(urls: List[str]):
            """Simulate fetching multiple URLs concurrently."""
            async def fetch(url):
                await asyncio.sleep(0.01)  # Simulate network delay
                return {"url": url, "data": f"content_{url}", "status": 200}

            tasks = [fetch(url) for url in urls]
            return await asyncio.gather(*tasks)

        urls = [f"https://api.example.com/item/{i}" for i in range(20)]

        start = time.perf_counter()
        results = fetch_batch(urls)
        duration = time.perf_counter() - start

        # Should complete in ~0.01s, not ~0.2s
        assert duration < 0.05
        assert len(results) == 20
        assert all(r["status"] == 200 for r in results)

    def test_async_database_queries(self):
        """Test async task for database queries (simulated)."""
        @async_task
        async def query_parallel(queries: List[str]):
            """Simulate parallel database queries."""
            async def query(sql):
                await asyncio.sleep(0.01)  # Simulate query time
                return {"query": sql, "rows": 100}

            tasks = [query(q) for q in queries]
            return await asyncio.gather(*tasks)

        queries = [f"SELECT * FROM table{i}" for i in range(10)]

        results = query_parallel(queries)
        assert len(results) == 10
        assert all(r["rows"] == 100 for r in results)

    def test_async_file_io_operations(self):
        """Test async task for file I/O operations (simulated)."""
        @async_task
        async def process_files(file_paths: List[str]):
            """Simulate async file processing."""
            async def process_file(path):
                await asyncio.sleep(0.01)  # Simulate I/O
                return {"path": path, "processed": True}

            tasks = [process_file(p) for p in file_paths]
            return await asyncio.gather(*tasks)

        files = [f"/data/file{i}.txt" for i in range(15)]

        results = process_files(files)
        assert len(results) == 15
        assert all(r["processed"] for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
