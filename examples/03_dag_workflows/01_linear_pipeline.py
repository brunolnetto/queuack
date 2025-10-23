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

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("linear")
queue = DuckQueue(db_path)

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

with queue.dag("etl_pipeline") as dag:
    e = dag.enqueue(extract, name="extract")
    t = dag.enqueue(transform, name="transform", depends_on="extract")
    l = dag.enqueue(load, name="load", depends_on="transform")

print("✓ DAG submitted. Execution order:")
execution_order = dag.get_execution_order()
for level, jobs in enumerate(execution_order):
    print(f"   Level {level}: {jobs}")
print()

# Execute the DAG jobs
print("🚀 Executing DAG jobs...")
print("Expected order: extract → transform → load")
print()
import time

processed = 0
while processed < 3:  # We expect 3 jobs
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
