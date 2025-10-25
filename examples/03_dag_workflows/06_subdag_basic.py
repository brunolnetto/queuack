"""Example: basic sub-DAG usage.

This example demonstrates proper separation of concerns:
- DAG: Defines workflow structure and submits jobs
- Worker: Processes the submitted jobs (including sub-DAG execution)
- Script: Coordinates DAG submission and worker management

The sub-DAG is implemented as a module-level factory function so it can be
enqueued and executed by the SubDAGExecutor sentinel flow.

Key Concepts:
- Sub-DAG factory pattern for composable workflows
- Manual worker management (proper separation of concerns)
- DAG completion monitoring and progress tracking
- Worker lifecycle control

Run:
    python examples/03_dag_workflows/06_subdag_basic.py

# Difficulty: intermediate
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DAG, DuckQueue, Worker


def sub_start():
    return "sub-start"


def sub_end():
    return "sub-end"


def create_subdag(queue: DuckQueue) -> DAG:
    """Module-level factory returning a small DAG. Picklable."""
    dag = DAG("subdag_basic", queue)
    dag.add_node(sub_start, name="sub_start")
    dag.add_node(sub_end, name="sub_end", depends_on="sub_start")
    return dag


def prepare():
    return "prepare"


def after_job():
    return "after"


def main():
    # Create queue with temporary database (safe for examples)
    db_path = create_temp_path("subdag_basic")
    queue = DuckQueue(db_path)

    print("🦆 SubDAG Basic Example")
    print("=======================")
    print(
        "This example demonstrates sub-DAG execution with proper separation of concerns:"
    )
    print("- Queue: Stores jobs")
    print("- DAG: Defines workflow and submits jobs")
    print("- Worker: Processes the submitted jobs")
    print("- Script: Coordinates everything (but doesn't auto-manage workers)")
    print()

    # 1. CREATE AND SUBMIT DAG
    print("📋 Step 1: Creating and submitting DAG...")
    dag = DAG("main_with_subdag", queue=queue)

    # Create a job that runs before the sub-DAG
    dag.add_node(prepare, name="prepare")

    # Add the sub-DAG; by default add_subdag uses SubDAGExecutor
    dag.add_node(create_subdag, name="run_subdag", depends_on="prepare")

    # Downstream job that waits for the sub-DAG sentinel
    dag.add_node(after_job, name="after", depends_on="run_subdag")

    start = time.perf_counter()
    run_id = dag.submit()
    elapsed = time.perf_counter() - start

    print(f"✅ Submitted DAG run_id={run_id[:8]} in {elapsed:.3f}s")
    print(f"   Jobs created: {len(dag.jobs)}")
    print()

    # 2. DEMONSTRATE PROPER SEPARATION OF CONCERNS
    print("👷 Step 2: Manual worker management (proper pattern)...")
    print("   Creating worker - this is the SCRIPT'S responsibility")
    print("   NOT the queue's responsibility (no auto-worker magic)")
    print()

    # Create worker - this demonstrates proper separation
    worker = Worker(queue, worker_id="subdag-demo", concurrency=1)

    print("🔄 Step 3: Processing jobs manually...")
    print("   This shows the claim/execute/ack cycle that happens inside worker.run()")
    print()

    # Simple manual processing to show the pattern
    jobs_processed = 0
    max_attempts = 20  # Prevent infinite loops

    for attempt in range(max_attempts):
        job = queue.claim(worker_id="subdag-demo")
        if job:
            jobs_processed += 1
            print(f"   📋 Processing job {jobs_processed}: {job.id[:8]}")

            try:
                result = job.execute()
                queue.ack(job.id, result=result, worker_id="subdag-demo")
                print(f"   ✅ Completed job {jobs_processed}")
            except Exception as e:
                queue.ack(job.id, error=str(e), worker_id="subdag-demo")
                print(f"   ❌ Failed job {jobs_processed}: {e}")
        else:
            # No jobs available, check if DAG is complete
            if dag.is_complete():
                break
            time.sleep(0.2)

    total_time = time.perf_counter() - start
    final_stats = queue.stats()

    print()
    print("🎉 Example completed!")
    print(f"   Total time: {total_time:.2f}s")
    print(f"   Jobs processed manually: {jobs_processed}")
    print(f"   Final DAG status: {dag.status.value}")
    print(f"   Queue stats: {final_stats}")
    print()
    print("💡 Key Takeaway:")
    print("   The SCRIPT manages workers, not the queue.")
    print("   This maintains clear separation of responsibilities.")


if __name__ == "__main__":
    main()
