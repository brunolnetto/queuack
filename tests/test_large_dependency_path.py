import time

from queuack import DAG, DuckQueue
from queuack.constants import VALUES_THRESHOLD


def noop():
    """Module-level no-op for pickling in tests."""
    return 1


def test_large_dependency_path():
    """Ensure the DAG submit uses the temp-table + chunked insert fallback
    path when dependency rows exceed VALUES_THRESHOLD and that all
    dependencies are inserted correctly (no duplicates).
    """
    # Choose size slightly above the threshold to force fallback
    n_children = VALUES_THRESHOLD + 10

    q = DuckQueue(":memory:")
    try:
        dag = DAG("large_deps", q)

        # Add a single parent job
        parent_id = dag.add_job(noop, name="parent")

        # Add many children depending on the parent
        for i in range(n_children):
            dag.add_job(noop, name=f"child_{i}", depends_on="parent")

        # Submit and time (we only need correctness here)
        start = time.perf_counter()
        run_id = dag.submit()
        elapsed = time.perf_counter() - start

        # Basic sanity
        assert run_id is not None

        # Check jobs count in DB: parent + children
        jobs = q.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE dag_run_id = ?",
            [dag._context.dag_run_id],
        ).fetchone()[0]
        q.conn.commit()

        assert jobs == n_children + 1

        # Check dependency rows count: each child should have one parent
        deps = q.conn.execute(
            "SELECT child_job_id, parent_job_id FROM job_dependencies WHERE child_job_id IN (SELECT id FROM jobs WHERE dag_run_id = ?)",
            [dag._context.dag_run_id],
        ).fetchall()
        q.conn.commit()

        # Build set to ensure there are no duplicate rows
        unique = set(deps)
        assert len(deps) == len(unique)
        # Each child should be present exactly once
        assert len(deps) == n_children

    finally:
        q.close()
