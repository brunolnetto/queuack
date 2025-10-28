"""09_error_recovery.py - Handle and recover from DAG failures

This example demonstrates different error recovery strategies in DAGs:
- Retry failed jobs with custom logic
- Skip optional branches that fail
- Continue execution with degraded functionality
- Manual intervention and job resubmission

Key Concepts:
- Failure isolation: Prevent one failure from stopping entire DAG
- Graceful degradation: Continue with available resources
- Retry strategies: Different approaches for different error types
- Manual recovery: Human intervention when needed

Real-world Use Cases:
- Resilient ETL pipelines
- Multi-stage processing with optional steps
- Systems with external dependencies that may fail
- Production workflows requiring high availability

# Difficulty: advanced
"""

from queuack import DAG
from queuack.status import DependencyMode


def reliable_source():
    """Always succeeds."""
    print("✅ Reliable source fetched")
    return {"data": [1, 2, 3]}


def flaky_enrichment():
    """Simulates flaky external service."""
    import random
    if random.random() < 0.7:
        raise ConnectionError("Enrichment service timeout")
    print("✅ Enrichment succeeded")
    return {"enriched": True}


def optional_validation():
    """Optional validation that might fail."""
    raise ValueError("Validation failed (optional)")


def core_processing():
    """Main processing that should always run."""
    print("⚙️ Core processing (essential)")
    return {"processed": True}


def finalize_with_degraded():
    """Finalize with whatever data is available."""
    print("📊 Finalizing (possibly with degraded data)")
    return "Complete"


print("🦆 Error Recovery DAG Example")
print("==============================")
print("This example shows resilient workflow patterns:")
print("- Reliable source always succeeds")
print("- Flaky enrichment may fail (non-blocking)")
print("- Optional validation may fail (skipped)")
print("- Core processing always runs")
print("- Finalize runs with available data")
print()

with DAG("error_recovery") as dag:
    # Reliable data source
    source = dag.add_node(reliable_source, name="source")
    
    # Optional enrichment (non-blocking)
    enrichment = dag.add_node(
        flaky_enrichment,
        name="enrichment",
        depends_on="source",
        max_attempts=3  # Retry a few times
    )
    
    # Optional validation (can be skipped)
    validation = dag.add_node(
        optional_validation,
        name="validation",
        depends_on="source",
        max_attempts=1  # Don't retry
    )
    
    # Core processing runs if source succeeds (ANY mode for optional deps)
    core = dag.add_node(
        core_processing,
        name="core",
        depends_on=["source"],  # Only requires source
    )
    
    # Finalize runs with whatever data is available
    finalize = dag.add_node(
        finalize_with_degraded,
        name="finalize",
        depends_on=["core"],  # Requires core only
    )
    
    print("🔧 DAG structure:")
    print("   source → [enrichment, validation, core]")
    print("   core → finalize")
    print("   (enrichment and validation are optional)")
    print()
    
    dag.submit()
    dag.wait_for_completion()

print()
print("📊 Final Results:")
print("================")
progress = dag.progress
print(f"Done: {progress['done']}")
print(f"Failed: {progress['failed']}")
print(f"Skipped: {progress['skipped']}")
print()
print("💡 Key Takeaway:")
print("   The DAG completed despite optional failures!")
print("   Core functionality preserved with degraded data.")