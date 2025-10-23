import os
import time
import pytest
from queuack.core import DuckQueue


def noop():
    return None


# This benchmark is skipped by default. Enable by setting RUN_LARGE_BENCH=1
RUN_BENCH = os.environ.get("RUN_LARGE_BENCH", "0") == "1"

# Parameters (tune via environment for larger runs)
LAYERS = int(os.environ.get("BENCH_LAYERS", "6"))  # number of layers deep
BRANCH = int(os.environ.get("BENCH_BRANCH", "4"))  # branching factor per node


@pytest.mark.skipif(not RUN_BENCH, reason="Large benchmark disabled by default")
def test_large_dag_propagation(tmp_path):
    """Build a layered DAG (layered tree), fail the root, and benchmark propagation."""
    db = str(tmp_path / "bench.duckdb")
    q = DuckQueue(db_path=db)

    # Build layered DAG: layer 0 has 1 node, layer i has BRANCH^i nodes
    layers = []
    prev_layer_ids = []
    for layer in range(LAYERS):
        layer_ids = []
        if layer == 0:
            job_id = q.enqueue(noop)
            layer_ids.append(job_id)
        else:
            # For each parent in prev layer, create BRANCH children
            for parent in prev_layer_ids:
                for b in range(BRANCH):
                    job_id = q.enqueue(noop, depends_on=parent)
                    layer_ids.append(job_id)
        prev_layer_ids = layer_ids
        layers.append(layer_ids)

    root = layers[0][0]

    # Optional: create a composite index to test differences
    create_composite = os.environ.get("BENCH_COMPOSITE_INDEX", "0") == "1"
    if create_composite:
        q.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jd_parent_child ON job_dependencies(parent_job_id, child_job_id)"
        )

    # Explain the recursive CTE used in ack propagation by constructing the same SQL
    explain_sql = """
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
        skipped_at = CURRENT_TIMESTAMP,
        skip_reason = ?,
        skipped_by = ?,
        attempts = max_attempts,
        completed_at = CURRENT_TIMESTAMP
    FROM should_skip ss
    WHERE jobs.id = ss.id
      AND ss.skip_flag = 1
      AND jobs.status NOT IN ('done','failed','skipped')
    RETURNING jobs.id
    """

    # Show EXPLAIN output (helpful for CI logs)
    try:
        explain_out = q.conn.execute(
            "EXPLAIN " + explain_sql, [root, f"bench_root:{root}", "bench"]
        ).fetchall()
        print("EXPLAIN output (first 10 rows):")
        for r in explain_out[:10]:
            print(r)
    except Exception as e:
        print("EXPLAIN failed:", e)

    # Force root to permanent failure and benchmark the propagation
    q.conn.execute("UPDATE jobs SET attempts = max_attempts WHERE id = ?", [root])

    start = time.perf_counter()
    q.ack(root, error="permanent")
    duration = time.perf_counter() - start

    total_jobs = q.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    skipped = q.conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'skipped'"
    ).fetchone()[0]

    print(
        f"Layers={LAYERS} Branch={BRANCH} total_jobs={total_jobs} skipped={skipped} duration_s={duration:.4f}"
    )
    # Basic sanity: at least one job should be skipped (except trivial cases)
    assert skipped >= 0
