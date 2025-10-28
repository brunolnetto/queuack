"""11_context_aware_tasks.py - Use TaskContext to access parent results

This example demonstrates context-aware task execution:
- Access parent task results without manual passing
- Use upstream() to get results by task name
- Build data pipelines where tasks depend on upstream data
- Avoid explicit result storage and retrieval

Key Concepts:
- TaskContext: Automatic dependency result access
- upstream(): Get parent results by name
- Data flow: Natural data passing between tasks
- Cleaner code: No manual result wiring

Real-world Use Cases:
- ETL pipelines where each stage needs previous results
- Multi-stage transformations
- Incremental processing workflows
- Any workflow with data dependencies

# Difficulty: intermediate
"""

from queuack import DAG
from queuack.data_models import TaskContext


def extract_data(context: TaskContext = None):
    """Extract raw data."""
    print("📥 Extracting data...")
    return {"records": [1, 2, 3, 4, 5], "count": 5}


def transform_data(context: TaskContext):
    """Transform using extracted data."""
    # Get result from extract task by name
    extracted = context.upstream("extract")
    print(f"⚙️ Transforming {extracted['count']} records...")
    
    records = extracted['records']
    transformed = [r * 2 for r in records]
    return {"records": transformed, "count": len(transformed)}


def validate_data(context: TaskContext):
    """Validate transformed data."""
    # Get result from transform task
    transformed = context.upstream("transform")
    print(f"✓ Validating {transformed['count']} records...")
    
    # Validation logic
    records = transformed['records']
    all_positive = all(r > 0 for r in records)
    return {"valid": all_positive, "count": len(records)}


def load_data(context: TaskContext):
    """Load validated data."""
    # Get results from both previous tasks
    transformed = context.upstream("transform")
    validation = context.upstream("validate")
    
    if not validation['valid']:
        raise ValueError("Data validation failed!")
    
    print(f"📤 Loading {transformed['count']} validated records...")
    return "Load complete"


print("🦆 Context-Aware Tasks Example")
print("================================")
print("This example shows tasks accessing parent results via TaskContext:")
print("- extract provides data")
print("- transform uses extract results")
print("- validate uses transform results")
print("- load uses both transform and validate results")
print()

with DAG("context_aware") as dag:
    dag.add_node(extract_data, name="extract")
    dag.add_node(transform_data, name="transform", depends_on="extract")
    dag.add_node(validate_data, name="validate", depends_on="transform")
    dag.add_node(load_data, name="load", depends_on=["transform", "validate"])
    
    print("✓ DAG submitted with context-aware tasks")
    print()
    
    dag.submit()
    dag.wait_for_completion()

print("\n🎉 Context-aware DAG completed!")
print()
print("💡 Key Benefits:")
print("   - No manual result passing")
print("   - Clean, readable task definitions")
print("   - Natural data flow between tasks")