"""Example: nested sub-DAGs.

This demonstrates a sub-DAG factory that itself contains another
sub-DAG. Factories must be module-level functions so they are picklable
when enqueued as SubDAGExecutor jobs.

# Difficulty: advanced

Run:
    python examples/03_dag_workflows/07_subdag_nested.py
"""

from queuack import DAG, DuckQueue


def inner_start():
    return "inner-start"


def inner_end():
    return "inner-end"


def outer_start():
    return "outer-start"


def outer_end():
    return "outer-end"


def start_job():
    return "top-start"


def finish_job():
    return "top-finish"


def create_inner(queue: DuckQueue) -> DAG:
    dag = DAG("inner", queue)
    dag.add_job(inner_start, name="inner_start")
    dag.add_job(inner_end, name="inner_end", depends_on="inner_start")
    return dag


def create_outer(queue: DuckQueue) -> DAG:
    dag = DAG("outer", queue)
    dag.add_node(outer_start, name="outer_start")

    # Add inner as a subdag inside outer
    dag.add_node(create_inner, name="inner_subdag", depends_on="outer_start")

    dag.add_node(outer_end, name="outer_end", depends_on="inner_subdag")
    return dag


def main():
    try:
        # Use context manager to start background workers automatically.
        with DAG("main_nested_subdags") as dag:
            dag.add_node(start_job, name="start")

            # Add outer which will add inner inside it
            dag.add_node(create_outer, name="outer_subdag", depends_on="start")

            dag.add_node(finish_job, name="finish", depends_on="outer_subdag")

            print("Submitting main DAG with nested sub-DAGs...")
            dag.submit()

            # Wait for completion
            dag.wait_for_completion(poll_interval=0.05)

            print("Nested DAG completed. Top-level jobs:")
            for j in dag.get_jobs():
                print(f"  {j['name']}: {j['status']}")
    except KeyboardInterrupt:
        print("Interrupted, exiting...")


if __name__ == "__main__":
    main()
