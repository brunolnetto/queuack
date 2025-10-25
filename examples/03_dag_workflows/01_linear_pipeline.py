"""
Linear Pipeline: Sequential Job Dependencies

This example demonstrates the most basic DAG pattern: a linear sequence of jobs
where each job depends on the successful completion of the previous job.

Pattern: A → B → C
- Job A runs first
- Job B runs only after A completes successfully
- Job C runs only after B completes successfully

Key Concepts:
- Sequential execution: Jobs run one after another
- Dependency chains: Each job waits for its predecessor
- Failure propagation: If any job fails, dependent jobs are skipped
- ETL workflows: Extract → Transform → Load is the classic example

Real-world Use Cases:
- Data pipelines (extract → clean → analyze → report)
- Document processing (download → parse → validate → store)
- Software builds (compile → test → package → deploy)
- Any sequential workflow with clear dependencies

Queuack Features Demonstrated:
- Basic DAG creation with queue.dag()
- Named jobs with human-readable identifiers
- depends_on parameter for dependency specification
- Automatic execution ordering
- Job status tracking and completion

# Difficulty: beginner
"""

from queuack import DAG

print("🦆 Linear Pipeline DAG Example")
print("==============================")
print("This example shows a basic sequential workflow:")
print("Extract → Transform → Load")
print()


def extract():
    print("📥 Extracting data...")
    return {"records": 100}


def transform():
    print("⚙️  Transforming data...")
    return {"processed": 100}


def load():
    print("📤 Loading data...")
    return "Success"


print("🔧 Building DAG with dependencies...")
print("   extract → transform → load")
print()

with DAG("etl_pipeline") as dag:
    e = dag.add_node(extract, name="extract")
    t = dag.add_node(transform, name="transform", depends_on="extract")
    l = dag.add_node(load, name="load", depends_on="transform")

    print("✓ DAG submitted. Execution order:")
    execution_order = dag.get_execution_order()
    for level, jobs in enumerate(execution_order):
        print(f"   Level {level}: {jobs}")
    print()

    dag.submit()
    dag.wait_for_completion(poll_interval=0.1)


print("\n🎉 DAG execution complete!")
