"""debugging_dags.py - Show how to inspect and debug DAG runs

# Difficulty: intermediate
"""

import os
import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, DAGRun, WorkerPool


def succeed(name: str):
    print(f"✅ {name} succeeded")
    return name


def fail(name: str):
    print(f"🔥 {name} will fail")
    raise RuntimeError(f"Task {name} failed for demonstration")

def wait_for_dag_completion(
    dr: DAGRun, 
    poll_timeout: float = 0.05, 
    timeout: int = 60
):
    start = time.time()

    # Start a short-lived worker pool in background to process jobs while we poll
    print("\nStarting local WorkerPool to process jobs (demo mode)")

    queue: DuckQueue = dr.queue

    # Use a couple of worker threads to increase throughput in demo mode
    pool = WorkerPool(queue, num_workers=2, concurrency=2)
    pool.start()

    try:
        while True:
            qstats = queue.stats()
            prog = dr.get_progress()
            print(f"queue.stats()={qstats} | dag.progress={prog}")

            pending = prog.get("pending", 0)
            claimed = prog.get("claimed", 0)
            if pending + claimed == 0:
                break

            if time.time() - start > timeout:
                print(f"Timeout waiting for DAG to finish after {timeout}s")
                break

            # Poll faster in demo mode
            time.sleep(poll_timeout)
    finally:
        pool.stop()

if __name__ == "__main__":
    db = create_temp_path("debug_dag")
    queue = DuckQueue(db)

    # Build a tiny DAG with one failing node using the higher-level DAG API
    dag = queue.create_dag("debugging_example")
    dag.add_job(succeed, args=("A",), name="A")
    dag.add_job(succeed, args=("B",), name="B", depends_on=["A"])
    dag.add_job(fail, args=("C",), name="C", depends_on=["B"])
    dag.add_job(succeed, args=("D",), name="D", depends_on=["C"])

    # Submit the DAG (creates a dag_run) and inspect before execution
    dag.submit()
    print("Submitted DAG run.")

    # Helpful: print DB path so an external worker can be started against the same DB
    print(f"Database path: {queue.db_path}")

    dr = DAGRun(queue, dag.dag_run_id)
    print("Initial DAG run status:", dr.get_status())
    print("Jobs:")
    for job in dr.get_jobs():
        print(job)

    wait_for_dag_completion(dr)

    # Re-inspect
    dr.update_status()
    print("Final status:", dr.get_status())
    print("Progress:", dr.get_progress())
    print("Jobs:")
    for job in dr.get_jobs():
        print(job)

    print("💡 Tip: use DAGRun.get_jobs() and get_progress() to locate failing nodes and debug payloads")

