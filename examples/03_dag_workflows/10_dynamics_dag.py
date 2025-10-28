"""10_dynamic_dag.py - Build DAGs dynamically at runtime

This example demonstrates dynamic DAG construction:
- Generate jobs based on runtime data
- Create parallel branches programmatically
- Scale workflows based on input size
- Use loops to build complex DAG structures

Key Concepts:
- Dynamic job creation: Jobs generated from data
- Programmatic DAG building: Use loops and conditionals
- Scalable workflows: Adapt to varying input sizes
- Metadata-driven workflows: Structure determined by config

Real-world Use Cases:
- Process variable number of files
- Handle dynamic customer lists
- Scale based on data partitions
- Multi-tenant processing

# Difficulty: intermediate
"""

from queuack import DAG


def process_item(item_id: int, item_data: str):
    """Process a single item."""
    print(f"⚙️ Processing item {item_id}: {item_data}")
    return f"Processed {item_id}"


def aggregate_results(count: int):
    """Aggregate results from all items."""
    print(f"📊 Aggregating {count} items")
    return f"Aggregated {count} items"


# Simulate runtime data
input_data = {
    1: "customer_data_1.csv",
    2: "customer_data_2.csv",
    3: "customer_data_3.csv",
    4: "customer_data_4.csv",
    5: "customer_data_5.csv",
}

print("🦆 Dynamic DAG Construction Example")
print("====================================")
print(f"Building DAG for {len(input_data)} items dynamically...")
print()

with DAG("dynamic_dag") as dag:
    job_names = []
    
    # Dynamically create processing jobs
    for item_id, data_path in input_data.items():
        job_name = f"process_{item_id}"
        dag.add_node(
            process_item,
            args=(item_id, data_path),
            name=job_name
        )
        job_names.append(job_name)
    
    # Aggregate waits for all processing jobs
    dag.add_node(
        aggregate_results,
        args=(len(input_data),),
        name="aggregate",
        depends_on=job_names  # All processing jobs
    )
    
    print(f"✓ Created {len(job_names)} processing jobs")
    print(f"✓ Created 1 aggregation job")
    print()
    print("Execution levels:", dag.get_execution_order())
    print()
    
    dag.submit()
    dag.wait_for_completion()

print("\n🎉 Dynamic DAG completed!")
print(f"Processed {len(input_data)} items dynamically")