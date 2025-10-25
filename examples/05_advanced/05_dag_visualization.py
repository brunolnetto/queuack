"""Realistic ETL pipeline DAG with data processing workflow.

# Difficulty: advanced
"""

import time
import json
import random
import os
from queuack import DuckQueue
from examples.utils.tempfile import create_temp_path


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f)


def _read_json(path):
    with open(path, "r") as f:
        return json.load(f)


def extract_data_task(base_dir: str, source_name: str):
    """Module-level extract task (picklable). Writes extraction to JSON and returns the path."""
    print(f"📥 Extracting data from {source_name}")
    # Simulate different data sources
    if "api" in source_name:
        if random.random() < 0.2:
            raise Exception(f"API {source_name} temporarily unavailable")
        data = {
            "source": source_name,
            "records": random.randint(100, 1000),
            "timestamp": time.time(),
            "data": [f"record_{i}" for i in range(random.randint(5, 15))],
        }
    elif "database" in source_name:
        data = {
            "source": source_name,
            "records": random.randint(500, 2000),
            "timestamp": time.time(),
            "data": [
                {"id": i, "value": random.random()}
                for i in range(random.randint(10, 30))
            ],
        }
    else:
        data = {
            "source": source_name,
            "records": random.randint(50, 500),
            "timestamp": time.time(),
            "data": [f"line_{i}_content" for i in range(random.randint(3, 10))],
        }

    out_path = os.path.join(base_dir, f"extract_{source_name}.json")
    _write_json(out_path, data)
    print(f"✅ Extracted {data['records']} records from {source_name} -> {out_path}")
    return out_path


def validate_data_task(base_dir: str, source_name: str):
    extract_path = os.path.join(base_dir, f"extract_{source_name}.json")
    data = _read_json(extract_path)
    print(f"🔍 Validating data from {data['source']}")
    if not data.get("data") or len(data["data"]) < 3:
        raise Exception("Insufficient or missing data in extraction")
    time.sleep(0.1)
    data["validated"] = True
    data["quality_score"] = random.uniform(0.8, 1.0)
    out = os.path.join(base_dir, f"validated_{source_name}.json")
    _write_json(out, data)
    print(f"✅ Validated data quality: {data['quality_score']:.2f} -> {out}")
    return out


def transform_data_task(base_dir: str, source_name: str):
    validated_path = os.path.join(base_dir, f"validated_{source_name}.json")
    validated = _read_json(validated_path)
    print(f"🔄 Transforming data from {validated['source']}")
    transformed = {
        "source": validated["source"],
        "original_records": validated["records"],
        "transformed_records": len(validated["data"]) * 2,
        "timestamp": time.time(),
        "data": [],
    }
    for i, record in enumerate(validated["data"]):
        if isinstance(record, dict):
            transformed["data"].append(
                {
                    "id": record["id"],
                    "transformed_value": record["value"] * 100,
                    "category": "A" if record["value"] > 0.5 else "B",
                }
            )
        else:
            transformed["data"].append(
                {"id": i, "content": str(record).upper(), "length": len(str(record))}
            )
    time.sleep(0.1)
    out = os.path.join(base_dir, f"transformed_{source_name}.json")
    _write_json(out, transformed)
    print(f"✅ Transformed {transformed['transformed_records']} records -> {out}")
    return out


def load_data_task(base_dir: str, source_name: str):
    transformed_path = os.path.join(base_dir, f"transformed_{source_name}.json")
    transformed = _read_json(transformed_path)
    print(f"📤 Loading data from {transformed['source']} to warehouse")
    time.sleep(0.1)
    if random.random() < 0.05:
        raise Exception("Warehouse connection failed")
    loaded = {
        "source": transformed["source"],
        "records_loaded": transformed["transformed_records"],
        "timestamp": time.time(),
        "status": "success",
        "load_id": f"LOAD_{int(time.time())}",
    }
    out = os.path.join(base_dir, f"loaded_{source_name}.json")
    _write_json(out, loaded)
    print(
        f"✅ Loaded {loaded['records_loaded']} records (ID: {loaded['load_id']}) -> {out}"
    )
    return out


def aggregate_results_task(base_dir: str, source_a: str, source_b: str, source_c: str):
    print("📊 Aggregating results from all sources")
    # Construct the expected file paths based on the source names
    sources = [source_a, source_b, source_c]
    load_files = [os.path.join(base_dir, f"loaded_{source}.json") for source in sources]

    la = _read_json(load_files[0])
    lb = _read_json(load_files[1])
    lc = _read_json(load_files[2])
    total = la["records_loaded"] + lb["records_loaded"] + lc["records_loaded"]
    aggregated = {
        "total_sources": 3,
        "total_records": total,
        "avg_records_per_source": total / 3,
        "processing_timestamp": time.time(),
        "pipeline_status": "completed",
    }
    out = os.path.join(base_dir, "aggregated_results.json")
    _write_json(out, aggregated)
    print(f"✅ Aggregated data from 3 sources ({total} total records) -> {out}")
    return out


class ETLProcessor:
    """Driver that wires module-level tasks into a DAG and runs them via the queue."""

    def __init__(self):
        self.db_path = create_temp_path("etl_dag")
        self.base_dir = os.path.splitext(self.db_path)[
            0
        ]  # Remove .db extension for directory
        os.makedirs(self.base_dir, exist_ok=True)
        self.queue = DuckQueue(self.db_path)

    def create_etl_pipeline_dag(self):
        """Create a realistic ETL pipeline DAG."""
        print("🏗️  Building ETL Pipeline DAG")
        print("=" * 50)

        with self.queue.dag("etl_pipeline") as dag:
            # Extract phase - parallel data sources
            api_extract = dag.enqueue(
                extract_data_task, args=(self.base_dir, "user_api"), name="extract_api"
            )

            db_extract = dag.enqueue(
                extract_data_task,
                args=(self.base_dir, "user_database"),
                name="extract_db",
            )

            file_extract = dag.enqueue(
                extract_data_task,
                args=(self.base_dir, "user_files"),
                name="extract_files",
            )

            # Validate phase - depends on extracts
            api_validate = dag.enqueue(
                validate_data_task,
                args=(self.base_dir, "user_api"),
                name="validate_api",
                depends_on="extract_api",
            )

            db_validate = dag.enqueue(
                validate_data_task,
                args=(self.base_dir, "user_database"),
                name="validate_db",
                depends_on="extract_db",
            )

            file_validate = dag.enqueue(
                validate_data_task,
                args=(self.base_dir, "user_files"),
                name="validate_files",
                depends_on="extract_files",
            )

            # Transform phase - depends on validation
            api_transform = dag.enqueue(
                transform_data_task,
                args=(self.base_dir, "user_api"),
                name="transform_api",
                depends_on="validate_api",
            )

            db_transform = dag.enqueue(
                transform_data_task,
                args=(self.base_dir, "user_database"),
                name="transform_db",
                depends_on="validate_db",
            )

            file_transform = dag.enqueue(
                transform_data_task,
                args=(self.base_dir, "user_files"),
                name="transform_files",
                depends_on="validate_files",
            )

            # Load phase - depends on transforms
            api_load = dag.enqueue(
                load_data_task,
                args=(self.base_dir, "user_api"),
                name="load_api",
                depends_on="transform_api",
            )

            db_load = dag.enqueue(
                load_data_task,
                args=(self.base_dir, "user_database"),
                name="load_db",
                depends_on="transform_db",
            )

            file_load = dag.enqueue(
                load_data_task,
                args=(self.base_dir, "user_files"),
                name="load_files",
                depends_on="transform_files",
            )

            # Final aggregation - depends on all loads
            final_aggregate = dag.enqueue(
                aggregate_results_task,
                args=(self.base_dir, "user_api", "user_database", "user_files"),
                name="aggregate_results",
                depends_on=["load_api", "load_db", "load_files"],
            )

        return dag

    def run_etl_demo(self):
        """Run the complete ETL pipeline demonstration."""
        print("🚀 ETL Pipeline DAG Demo")
        print("=" * 50)

        # Create the ETL DAG
        dag = self.create_etl_pipeline_dag()

        # Export and display the DAG visualization
        mermaid = dag.export_mermaid()
        print("\n📈 Pipeline DAG Structure:")
        print(mermaid)

        # Save visualization
        with open("etl_pipeline.md", "w") as f:
            f.write("# ETL Pipeline DAG\n\n")
            f.write("```mermaid\n")
            f.write(mermaid)
            f.write("\n```\n\n")
            f.write("## Pipeline Overview\n")
            f.write("- **Extract**: Parallel data extraction from multiple sources\n")
            f.write("- **Validate**: Data quality checks\n")
            f.write("- **Transform**: Data processing and enrichment\n")
            f.write("- **Load**: Data warehouse loading\n")
            f.write("- **Aggregate**: Final results aggregation\n")

        print("📄 DAG visualization saved to etl_pipeline.md")

        # Execute the pipeline
        print("\n🏃 Executing ETL Pipeline...")
    start_time = time.perf_counter()

        # Process all jobs in the DAG by claiming/executing/acking manually
        jobs_completed = 0
        total_jobs = len(dag.jobs)

        while jobs_completed < total_jobs:
            job = self.queue.claim(worker_id="etl-worker")
            if not job:
                time.sleep(0.1)
                continue

            try:
                result = job.execute()
                self.queue.ack(job.id, result=result)
                jobs_completed += 1
                print(f"[{jobs_completed}/{total_jobs}] Job {job.id[:8]} -> {result}")
            except Exception as e:
                # ack with error so retries/skipped states are handled by core
                self.queue.ack(job.id, error=f"{type(e).__name__}: {e}")
                jobs_completed += 1
                print(f"[{jobs_completed}/{total_jobs}] Job {job.id[:8]} failed: {e}")

    total_time = time.perf_counter() - start_time

        # Display results
        print("📊 ETL Pipeline Results:")
        print(f"Total jobs: {total_jobs}")
        print(f"Jobs processed: {jobs_completed}")

        # Try to read aggregated results file
        agg_path = os.path.join(self.base_dir, "aggregated_results.json")
        if os.path.exists(agg_path):
            agg = _read_json(agg_path)
            print(f"Sources processed: {agg['total_sources']}")
            print(f"Total records: {agg['total_records']}")

        print("\n✅ ETL pipeline completed successfully!")
        print("\nKey features demonstrated:")
        print("• Complex DAG with parallel and sequential execution")
        print("• Error handling and data validation")
        print("• Realistic ETL workflow simulation")
        print("• Dependency management across pipeline stages")


def main():
    etl = ETLProcessor()
    etl.run_etl_demo()


if __name__ == "__main__":
    main()
