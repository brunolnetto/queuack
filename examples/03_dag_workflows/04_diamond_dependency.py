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

from queuack import DAG


def task_func(node_name: str) -> None:
    print(f"⚙️ Processing {node_name} task")


with DAG("diamond") as dag:
    start = dag.add_node(task_func, args=("Start",), name="start")
    left = dag.add_node(task_func, args=("Left",), name="left", depends_on="start")
    right = dag.add_node(task_func, args=("Right",), name="right", depends_on="start")
    end = dag.add_node(
        task_func, args=("End",), name="end", depends_on=["left", "right"]
    )

    print("Execution levels:", dag.get_execution_order())
    # [['start'], ['left', 'right'], ['end']]

    # Submit and wait for completion
    dag.submit()

    dag.wait_for_completion()


print("\n🎉 DAG execution complete!")
