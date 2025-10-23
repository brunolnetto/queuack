"""
Conditional Execution: OR-Based Dependencies

This example demonstrates conditional job execution using DependencyMode.ANY.
Instead of requiring ALL dependencies to succeed, jobs can run when ANY
dependency succeeds, enabling flexible workflow logic.

Pattern:
    validate_source_a ─┐
                       ├→ process (ANY mode)
    validate_source_b ─┘

Execution Logic:
- validate_source_a and validate_source_b run in parallel
- If EITHER validation succeeds, the 'process' job runs
- If BOTH validations fail, 'process' is skipped
- This enables fallback scenarios and optional dependencies

Key Concepts:
- DependencyMode.ANY: Job runs if ANY dependency succeeds
- DependencyMode.ALL: Job runs only if ALL dependencies succeed (default)
- Conditional workflows: Different execution paths based on results
- Failure tolerance: System continues with available resources
- Fallback logic: Use alternative data sources or processing methods

Real-world Use Cases:
- Multi-source data ingestion (use any available data source)
- Backup systems (try primary, fallback to secondary)
- Optional preprocessing (run if data quality check passes)
- A/B testing (run analysis on either test group)
- Service redundancy (use any available service instance)

Queuack Features Demonstrated:
- DependencyMode.ANY for conditional execution
- Parallel validation jobs
- Failure handling and job skipping
- Flexible dependency logic
- Status propagation and descendant management

Advanced Topics:
- Failure propagation: Failed jobs can mark descendants as skipped
- Retry logic: Jobs can be retried before being marked as permanently failed
- Status tracking: Monitor job states and dependency resolution

# Difficulty: advanced
"""

from queuack import DuckQueue
from queuack.status import DependencyMode

queue = DuckQueue("conditional.db")


def validate_source(source_name):
    # Simulate: source A fails, source B succeeds
    if source_name == "A":
        raise Exception("Source A unavailable")
    print(f"✓ Source {source_name} validated")
    return True


def process_data():
    print("Processing data from available source")
    return "Success"


with queue.dag("conditional_dag") as dag:
    validate_a = dag.enqueue(validate_source, args=("A",), name="validate_a")
    validate_b = dag.enqueue(validate_source, args=("B",), name="validate_b")

    # Process if ANY source validates
    process = dag.enqueue(
        process_data,
        name="process",
        depends_on=["validate_a", "validate_b"],
        dependency_mode=DependencyMode.ANY,
    )

print("✓ Conditional DAG submitted (ANY mode)")

# Execute the DAG jobs
print("\n🚀 Executing DAG jobs...")
import time

processed = 0
empty_polls = 0
max_empty_polls = 3

while empty_polls < max_empty_polls:
    job = queue.claim()
    if job:
        processed += 1
        empty_polls = 0  # Reset counter
        print(f"📋 Processing job #{processed}: {job.id[:8]}")

        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✅ Completed job #{processed}")
        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"❌ Failed job #{processed}: {e}")
    else:
        empty_polls += 1
        if empty_polls == 1:
            print("⏳ Waiting for jobs...")
        time.sleep(0.5)

print(f"\n🎉 DAG execution complete! Processed {processed} jobs.")
