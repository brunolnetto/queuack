"""
Diamond Dependency: Parallel Branches with Synchronization

This example demonstrates the diamond dependency pattern: a job splits into two
parallel branches that execute concurrently, then converge back to a single
synchronization point.

Pattern:
       start
      ↙    ↘
    left   right
      ↘    ↙
       end

Execution Flow:
1. 'start' runs first (entry point)
2. 'left' and 'right' run in parallel after 'start' completes
3. 'end' runs only after BOTH 'left' AND 'right' complete (synchronization)

Key Concepts:
- Parallel execution: Multiple jobs running simultaneously
- Synchronization: Diamond tip waits for all parallel branches
- Dependency convergence: Multiple dependencies merging into one
- Execution levels: Jobs organized by dependency depth
- Load balancing: Distribute work across different processing paths

Real-world Use Cases:
- Data validation pipelines (validate format + validate content in parallel)
- Multi-stage processing (preprocess data + prepare environment in parallel)
- Quality assurance (run tests + run linting in parallel, then report)
- CI/CD pipelines (build + test in parallel, then deploy)
- Financial workflows (process payments + update ledger in parallel)

Queuack Features Demonstrated:
- Multiple dependencies with depends_on=[list]
- Parallel job execution within DAG
- Automatic synchronization points
- Execution order visualization with get_execution_order()
- Job naming and dependency management

Advanced Topics:
- Complex dependency graphs: Building more intricate workflows
- Performance optimization: Parallelizing independent tasks
- Resource management: Balancing load across parallel branches
- Monitoring and debugging: Tracking execution in complex DAGs

# Difficulty: advanced
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("diamond")
queue = DuckQueue(db_path)


def task_func(node_name: str) -> None:
    print(f"⚙️ Processing {node_name} task")


with queue.dag("diamond") as dag:
    start = dag.enqueue(task_func, args=("Start",), name="start")
    left = dag.enqueue(task_func, args=("Left",), name="left", depends_on="start")
    right = dag.enqueue(task_func, args=("Right",), name="right", depends_on="start")
    end = dag.enqueue(
        task_func, args=("End",), name="end", depends_on=["left", "right"]
    )

print("Execution levels:", dag.get_execution_order())
# [['start'], ['left', 'right'], ['end']]

# Execute the DAG jobs
print("\n🚀 Executing DAG jobs...")
import time

processed = 0
expected_jobs = 4  # start + left + right + end
while processed < expected_jobs:
    job = queue.claim()
    if job:
        processed += 1
        print(f"📋 Processing job #{processed}: {job.id[:8]}")

        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✅ Completed job #{processed}")
        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"❌ Failed job #{processed}: {e}")
    else:
        print("⏳ Waiting for jobs...")
        time.sleep(0.5)

print("\n🎉 DAG execution complete!")
