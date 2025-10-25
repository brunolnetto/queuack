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

from queuack import DAG


def external_processing_func() -> None:
    print("📥 External preprocessing")


def main_processing_func() -> None:
    print("⚙️ Main processing")


def finalize_func() -> None:
    print("📤 Finalize")


with DAG("depends_on_external") as dag:
    # Create an external job first on the same queue used by the DAG
    external_job_id = dag.queue.enqueue(
        external_processing_func
    )

    print(f"📋 Created external job: {external_job_id[:8]}")

    # DAG depends on external job
    # Reference external job by ID
    process = dag.add_node(
        main_processing_func,
        name="process",
        depends_on=external_job_id,  # UUID string
    )

    finalize = dag.add_node(finalize_func, name="finalize", depends_on="process")

    dag.submit()
    print("✓ DAG with external dependency submitted")

    dag.wait_for_completion()

print("\n🎉 DAG execution complete!")
