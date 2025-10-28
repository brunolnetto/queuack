"""
External Dependencies: Referencing Jobs Outside DAG Context

This example demonstrates how to create dependencies on jobs that were enqueued
outside of the DAG context. This allows mixing manual job creation with
structured DAG workflows, enabling hybrid approaches to job management.

Pattern:
   [External Job] → DAG Job → DAG Job
       ↑
   (manual enqueue)

Execution Flow:
1. External job is created manually using queue.enqueue()
2. DAG is created with jobs that depend on the external job's ID
3. DAG jobs run only after the external job completes successfully
4. This enables integration with existing job queues or manual workflows

Key Concepts:
- External job references: Using job IDs from outside the DAG
- Hybrid workflows: Combining manual and automated job creation
- Dependency injection: Passing job IDs into DAG definitions
- Job lifecycle management: Tracking jobs across different contexts
- Workflow composition: Building complex systems from simpler parts

Real-world Use Cases:
- Legacy system integration (depend on jobs from old queue systems)
- Manual approval workflows (DAG waits for human approval job)
- Event-driven processing (DAG triggered by external event jobs)
- Microservice coordination (jobs from different services in one workflow)
- Scheduled maintenance (DAG depends on manual maintenance jobs)

Queuack Features Demonstrated:
- Manual job enqueueing with queue.enqueue()
- DAG dependencies on external job IDs (UUID strings)
- Job ID retrieval and passing between contexts
- Mixed execution environments (manual + DAG)
- Status tracking across different job creation methods

Advanced Topics:
- Job ID management: Storing and retrieving job identifiers
- Cross-context dependencies: Linking jobs from different systems
- Workflow orchestration: Coordinating disparate job sources
- Error handling: Managing failures in hybrid environments
- Monitoring complexity: Tracking jobs across multiple contexts

# Difficulty: advanced
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("external")
queue = DuckQueue(db_path)


def external_processing_func() -> None:
    print("📥 External preprocessing")


def main_processing_func() -> None:
    print("⚙️ Main processing")


def finalize_func() -> None:
    print("📤 Finalize")


# Create an external job first
external_job_id = queue.enqueue(
    external_processing_func
    # Removed queue="preprocessing" to use default queue
)

print(f"📋 Created external job: {external_job_id[:8]}")

# DAG depends on external job
with queue.dag("depends_on_external") as dag:
    # Reference external job by ID
    process = dag.enqueue(
        main_processing_func,
        name="process",
        depends_on=external_job_id,  # UUID string
    )

    finalize = dag.enqueue(finalize_func, name="finalize", depends_on="process")

print("✓ DAG with external dependency submitted")

# Execute the DAG jobs
print("\n🚀 Executing DAG jobs...")
import time

processed = 0
expected_jobs = 3  # external + process + finalize
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
