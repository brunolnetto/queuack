"""
Spark ETL example using TaskContext for clean data passing.

This demonstrates the recommended pattern for multi-step pipelines:
- Tasks declare a 'context' parameter to receive TaskContext
- Use context.upstream("task_name") to get parent results
- No manual job ID passing required

Pattern: extract -> spark_transform -> load

# Difficulty: advanced (integration)
"""

import json
import os
import uuid
from datetime import datetime

from queuack import DAG, TaskContext

RESULTS_DIR = "results_spark"


# ============================================================================
# Task Functions (all module-level for pickling)
# ============================================================================


def extract():
    """Simulate extracting rows of data.

    Returns a list of dicts representing rows. With the context system,
    we can return data directly - no manual file writing needed unless
    the data is truly large.
    """
    print("📥 Extracting sample data for Spark ETL...")
    rows = []
    for i in range(20):
        rows.append({"id": i, "value": i * 2, "group": "even" if i % 2 == 0 else "odd"})
    print(f"✅ Extracted {len(rows)} rows")
    return rows


def spark_transform(context: TaskContext):
    """Transform the input rows using PySpark if available.

    Uses context.upstream() to automatically get the parent task result.
    No manual job ID passing needed!

    Args:
        context: Automatically injected TaskContext
    """
    # Get data from upstream extract task
    rows = context.upstream("extract")

    print(f"🚀 Received {len(rows)} rows from extract task")

    try:
        from pyspark.sql import Row, SparkSession

        print("🚀 Running transform with PySpark (local mode)...")
        spark = (
            SparkSession.builder.master("local[1]")
            .appName("queuack-spark-example")
            .getOrCreate()
        )

        # Convert list of dicts to DataFrame
        rdd = spark.sparkContext.parallelize(rows)
        df = rdd.map(lambda d: Row(**d)).toDF()

        # Example transform: compute value_squared and filter
        from pyspark.sql.functions import col, pow

        out = df.withColumn("value_squared", pow(col("value"), 2)).filter(
            col("value") >= 10
        )

        result = [row.asDict() for row in out.collect()]

        # Stop the session to avoid leaking resources
        spark.stop()

        print(f"✅ Spark transform produced {len(result)} rows")
        return result

    except Exception as e:
        # Fallback path when pyspark isn't available
        print(f"⚠️ PySpark not available, using Python fallback: {e}")
        transformed = [
            dict(r, value_squared=r["value"] ** 2) for r in rows if r["value"] >= 10
        ]
        print(f"✅ Fallback transform produced {len(transformed)} rows")
        return transformed


def load(context: TaskContext):
    """Persist results to results_spark directory as JSON.

    Uses context.upstream() to get the transform task result.

    Args:
        context: Automatically injected TaskContext

    Returns:
        Path to output file
    """
    # Get transformed data from upstream task
    results = context.upstream("spark_transform")

    print(f"📦 Loading {len(results)} results...")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(
        RESULTS_DIR, f"spark_etl_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    )

    with open(out_path, "w") as f:
        json.dump(results, f, default=str, indent=2)

    print(f"✅ Saved results to {out_path}")
    return out_path


# ============================================================================
# Large Data Variant (for truly large datasets)
# ============================================================================


def extract_large():
    """Extract large dataset - write to disk and return path.

    For datasets > 1MB, it's better to write to disk and pass file paths
    to avoid database bloat.
    """
    print("📥 Extracting large dataset...")

    # Simulate large dataset
    rows = []
    for i in range(10000):  # Larger dataset
        rows.append({"id": i, "value": i * 2, "group": "even" if i % 2 == 0 else "odd"})

    # Write to disk
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"extract_{uuid.uuid4().hex[:8]}.json")
    with open(path, "w") as f:
        json.dump(rows, f, default=str)

    print(f"📁 Wrote {len(rows)} rows to {path}")
    return path  # Return path (small string)


def spark_transform_large(context: TaskContext):
    """Transform large dataset - read from path, write to new path.

    Args:
        context: Automatically injected TaskContext
    """
    # Get file path from upstream task
    input_path = context.upstream("extract_large")

    print(f"🚀 Reading data from {input_path}")
    with open(input_path) as f:
        rows = json.load(f)

    print(f"🚀 Transforming {len(rows)} rows with Spark...")

    try:
        from pyspark.sql import Row, SparkSession
        from pyspark.sql.functions import col, pow

        spark = (
            SparkSession.builder.master("local[1]")
            .appName("queuack-spark-large")
            .getOrCreate()
        )

        rdd = spark.sparkContext.parallelize(rows)
        df = rdd.map(lambda d: Row(**d)).toDF()
        out = df.withColumn("value_squared", pow(col("value"), 2)).filter(
            col("value") >= 100
        )

        result = [row.asDict() for row in out.collect()]
        spark.stop()

        print(f"✅ Spark transform produced {len(result)} rows")

    except Exception as e:
        print(f"⚠️ Spark unavailable: {e}")
        result = [
            dict(r, value_squared=r["value"] ** 2) for r in rows if r["value"] >= 100
        ]

    # Write result to disk
    output_path = os.path.join(RESULTS_DIR, f"transform_{uuid.uuid4().hex[:8]}.json")
    with open(output_path, "w") as f:
        json.dump(result, f, default=str)

    print(f"📁 Wrote {len(result)} rows to {output_path}")
    return output_path  # Return path


def load_large(context: TaskContext):
    """Load from file path.

    Args:
        context: Automatically injected TaskContext
    """
    # Get file path from upstream
    input_path = context.upstream("spark_transform_large")

    print(f"📦 Reading results from {input_path}")
    with open(input_path) as f:
        results = json.load(f)

    print(f"📦 Loaded {len(results)} results")

    # Final output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = os.path.join(RESULTS_DIR, f"spark_etl_large_{timestamp}.json")

    with open(final_path, "w") as f:
        json.dump(results, f, default=str, indent=2)

    print(f"✅ Saved final results to {final_path}")
    return final_path


# ============================================================================
# Main Execution
# ============================================================================

if __name__ == "__main__":
    print("🦆 Queuack + Spark ETL Example (with TaskContext)")
    print("=" * 60)

    # Example 1: Small dataset (data passes through DB)
    print("\n📊 Example 1: Small Dataset (automatic data passing)")
    print("-" * 60)

    with DAG("spark_etl_small", description="Small dataset example") as dag:
        dag.add_node(extract, name="extract")
        dag.add_node(spark_transform, name="spark_transform", depends_on="extract")
        dag.add_node(load, name="load", depends_on="spark_transform")

        dag.submit()
        dag.wait_for_completion(poll_interval=0.5)

    print(f"\n✅ Small dataset DAG complete. Status: {dag.status.value}")

    # Example 2: Large dataset (file paths passed through DB)
    print("\n📊 Example 2: Large Dataset (file path passing)")
    print("-" * 60)

    with DAG("spark_etl_large", description="Large dataset example") as dag:
        dag.add_node(extract_large, name="extract_large")
        dag.add_node(
            spark_transform_large,
            name="spark_transform_large",
            depends_on="extract_large",
        )
        dag.add_node(load_large, name="load_large", depends_on="spark_transform_large")

        dag.submit()
        dag.wait_for_completion(poll_interval=0.5)

    print(f"\n✅ Large dataset DAG complete. Status: {dag.status.value}")

    print("\n" + "=" * 60)
    print("🎉 All examples complete!")
    print(f"📁 Check {RESULTS_DIR}/ for output files")
