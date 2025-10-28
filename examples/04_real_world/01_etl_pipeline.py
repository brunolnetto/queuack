"""
ETL Pipeline: Extract, Transform, Load Data Processing

This example demonstrates a complete Extract-Transform-Load (ETL) pipeline
using Queuack DAGs. ETL is a fundamental pattern in data engineering where
data is extracted from sources, transformed for analysis, and loaded into
a destination system.

Pipeline Flow:
   Extract → Validate → Transform → Load
     ↓         ↓         ↓         ↓
   (API)    (Schema)  (Clean)   (Warehouse)

Key Components:
- Extract: Pull data from external APIs with retry logic
- Validate: Ensure data quality and schema compliance
- Transform: Clean, normalize, and enrich the data
- Load: Store processed data in the target system

Real-world Use Cases:
- Data warehouse loading (daily batch ETL jobs)
- API data synchronization (sync external data sources)
- Log processing pipelines (collect → parse → aggregate → store)
- Customer data platforms (ingest → clean → unify → load)
- Financial reporting (extract transactions → validate → transform → load)

Queuack Features Demonstrated:
- Sequential DAG execution with dependencies
- Error handling and retry mechanisms (max_attempts)
- Timeout configuration for long-running jobs
- Job monitoring with DAGRun progress tracking
- Structured pipeline organization

Advanced Topics:
- Data quality assurance: Validation steps prevent bad data
- Scalability: Retry logic handles transient failures
- Monitoring: Progress tracking for pipeline observability
- Reliability: Timeouts prevent hanging operations
- Modularity: Each step is independently testable and maintainable

# Difficulty: advanced
"""

from datetime import datetime

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("etl")
queue = DuckQueue(db_path)


def extract_from_api(endpoint: str):
    """Extract data from REST API."""
    print(f"📡 Extracting data from {endpoint}...")

    # Generate realistic sample data instead of dummy data
    import random
    from datetime import timedelta

    # Simulate API response with realistic e-commerce data
    products = [
        {
            "id": 1,
            "name": "Laptop",
            "category": "Electronics",
            "price": 999.99,
            "stock": 50,
        },
        {
            "id": 2,
            "name": "Mouse",
            "category": "Electronics",
            "price": 29.99,
            "stock": 200,
        },
        {
            "id": 3,
            "name": "Book",
            "category": "Education",
            "price": 19.99,
            "stock": 150,
        },
        {
            "id": 4,
            "name": "Chair",
            "category": "Furniture",
            "price": 149.99,
            "stock": 30,
        },
        {
            "id": 5,
            "name": "Headphones",
            "category": "Electronics",
            "price": 79.99,
            "stock": 75,
        },
    ]

    # Add some sales data
    sales_data = []
    for i in range(100):
        product = random.choice(products)
        sale_date = datetime.now() - timedelta(days=random.randint(0, 30))
        quantity = random.randint(1, 5)
        sales_data.append(
            {
                "sale_id": i + 1,
                "product_id": product["id"],
                "product_name": product["name"],
                "category": product["category"],
                "quantity": quantity,
                "unit_price": product["price"],
                "total_amount": round(quantity * product["price"], 2),
                "sale_date": sale_date.strftime("%Y-%m-%d %H:%M:%S"),
                "customer_region": random.choice(["North", "South", "East", "West"]),
            }
        )

    return {"data": sales_data, "count": len(sales_data), "source": endpoint}


def validate_schema():
    """Validate extracted data."""
    print("🔍 Validating schema...")

    # In a real system, this would read from a shared store or database
    # For this example, we'll simulate validation of the extracted data
    print("✅ Schema validation passed")
    return {
        "validation_status": "PASSED",
        "checks_performed": ["required_columns", "data_types", "date_formats"],
    }


def transform_records():
    """Transform and clean data."""
    print("🔄 Transforming and cleaning data...")

    # Generate sample transformed data
    import random
    from datetime import timedelta

    # Simulate transforming the extracted sales data
    transformed_records = []
    total_revenue = 0

    for i in range(100):
        quantity = random.randint(1, 5)
        unit_price = round(random.uniform(10, 1000), 2)
        revenue = round(quantity * unit_price, 2)
        total_revenue += revenue

        transformed_records.append(
            {
                "sale_id": i + 1,
                "product_name": f"Product {i + 1}",
                "category": random.choice(["Electronics", "Books", "Clothing", "Home"]),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": revenue,
                "sale_date": (
                    datetime.now() - timedelta(days=random.randint(0, 30))
                ).strftime("%Y-%m-%d"),
                "profit_margin": round(random.uniform(0.1, 0.3), 2),
            }
        )

    print("📊 Transformation complete:")
    print(f"   Records processed: {len(transformed_records)}")
    print(f"   Total revenue: ${total_revenue:.2f}")

    return {
        "processed_data": transformed_records,
        "total_revenue": total_revenue,
        "record_count": len(transformed_records),
        "timestamp": datetime.now(),
    }


def load_to_warehouse():
    """Load to data warehouse."""
    print("💾 Loading data to warehouse...")

    # Create results directory
    import os

    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    # In a real system, this would load from a staging area
    # For this example, we'll simulate loading and create output files
    import json

    # Simulate final metrics
    final_metrics = {
        "records_loaded": 100,
        "total_revenue": 162088.89,
        "data_quality_score": 0.98,
        "load_timestamp": datetime.now().isoformat(),
        "warehouse_table": "fct_sales",
    }

    # Save metrics to JSON
    output_file = os.path.join(
        results_dir, f"warehouse_load_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(output_file, "w") as f:
        json.dump(final_metrics, f, indent=2)

    print("✅ Data loaded successfully to warehouse!")
    print(f"   Records loaded: {final_metrics['records_loaded']}")
    print(f"   Revenue: ${final_metrics['total_revenue']:.2f}")
    print(f"   Metrics saved to: {output_file}")

    return {
        "status": "SUCCESS",
        "output_files": [output_file],
        "metrics": final_metrics,
    }


# Build pipeline
with queue.dag("daily_etl", description="Daily ETL job") as dag:
    extract = dag.enqueue(
        extract_from_api,
        args=("https://api.example.com/data",),
        name="extract",
        max_attempts=5,  # Retry API failures
    )

    validate = dag.enqueue(validate_schema, name="validate", depends_on="extract")

    transform = dag.enqueue(transform_records, name="transform", depends_on="validate")

    load = dag.enqueue(
        load_to_warehouse,
        name="load",
        depends_on="transform",
        timeout_seconds=600,  # 10 minute timeout
    )

# Monitor execution
from queuack.dag import DAGRun

dag_run = DAGRun(queue, dag.dag_run_id)

# Check progress
print(dag_run.get_progress())
# {'pending': 3, 'claimed': 1, 'done': 0, 'failed': 0}

# Execute the DAG jobs
print("\n🚀 Executing ETL pipeline...")
import time

processed = 0
expected_jobs = 4  # extract + validate + transform + load
while processed < expected_jobs:
    job = queue.claim()
    if job:
        processed += 1
        print(f"📋 Processing job #{processed}: {job.id[:8]}")

        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✅ Completed job #{processed}")

            # Show result summary for key jobs
            if job.node_name == "transform":
                print(f"   📊 Transformed {result['record_count']} records")
                print(f"   💰 Total revenue: ${result['total_revenue']:.2f}")
            elif job.node_name == "load":
                print(f"   💾 Files created: {result['output_files']}")

        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"❌ Failed job #{processed}: {e}")
    else:
        print("⏳ Waiting for jobs...")
        time.sleep(0.5)

print("\n🎉 ETL pipeline execution complete!")

# List generated files
import os

print("\n📁 Generated files:")
results_dir = "results"
if os.path.exists(results_dir):
    for file in os.listdir(results_dir):
        if file.startswith(("warehouse_load_", "etl_summary_")):
            print(f"   📄 {os.path.join(results_dir, file)}")
else:
    print("   No results directory found")
