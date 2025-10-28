"""12_branching_workflows.py - Conditional branching based on results

This example demonstrates workflow branching:
- Different execution paths based on intermediate results
- Conditional job execution
- Multi-path workflows
- Result-driven routing

Note: This is a simplified example showing the pattern.
Full conditional branching would require custom logic in workers.

Key Concepts:
- Workflow branching: Different paths based on conditions
- Result-driven execution: Route based on data
- Multi-outcome workflows: Handle different scenarios
- Flexible pipelines: Adapt to runtime conditions

Real-world Use Cases:
- Quality checks with pass/fail paths
- A/B testing workflows
- Multi-stage approval processes
- Environment-specific deployments

# Difficulty: advanced
"""

from queuack import DAG
from queuack.status import DependencyMode


def quality_check():
    """Check data quality."""
    print("🔍 Running quality check...")
    # Simulate quality score
    quality_score = 85
    
    if quality_score >= 80:
        print(f"✅ Quality check passed (score: {quality_score})")
        return {"passed": True, "score": quality_score}
    else:
        print(f"❌ Quality check failed (score: {quality_score})")
        return {"passed": False, "score": quality_score}


def standard_processing():
    """Process high-quality data normally."""
    print("⚙️ Standard processing (high quality data)")
    return "Standard processing complete"


def enhanced_cleaning():
    """Enhanced cleaning for low-quality data."""
    print("🧹 Enhanced cleaning (low quality data)")
    return "Enhanced cleaning complete"


def alternative_processing():
    """Alternative processing after cleaning."""
    print("⚙️ Alternative processing (cleaned data)")
    return "Alternative processing complete"


def finalize():
    """Finalize regardless of path taken."""
    print("📊 Finalizing results")
    return "Finalized"


print("🦆 Branching Workflow Example")
print("==============================")
print("This example shows conditional workflow paths:")
print()
print("            quality_check")
print("           /              \\")
print("    standard_proc    enhanced_clean")
print("           \\              /")
print("                finalize")
print()

with DAG("branching") as dag:
    # Quality check determines the path
    check = dag.add_node(quality_check, name="quality_check")
    
    # Path 1: High quality → standard processing
    standard = dag.add_node(
        standard_processing,
        name="standard",
        depends_on="quality_check",
        max_attempts=1  # Don't retry if condition not met
    )
    
    # Path 2: Low quality → enhanced cleaning → alternative processing
    cleaning = dag.add_node(
        enhanced_cleaning,
        name="cleaning",
        depends_on="quality_check",
        max_attempts=1
    )
    
    alternative = dag.add_node(
        alternative_processing,
        name="alternative",
        depends_on="cleaning"
    )
    
    # Final step runs if ANY path succeeds
    finalize_job = dag.add_node(
        finalize,
        name="finalize",
        depends_on=["standard", "alternative"],
        dependency_mode=DependencyMode.ANY
    )
    
    print("✓ Branching workflow created")
    print()
    
    dag.submit()
    dag.wait_for_completion()

print("\n🎉 Branching workflow completed!")
print()
print("💡 Note:")
print("   In this demo, both paths execute because jobs don't have")
print("   conditional logic. For true branching, implement condition")
print("   checks in task code and raise exceptions to skip branches.")