"""
Fan-out/Fan-in: Parallel Processing with Synchronization

This example demonstrates the fan-out/fan-in pattern: one job splits into multiple
parallel jobs, which then converge back to a single synchronization point.

Pattern:
       extract
      ├─→ process_a ─┐
      ├─→ process_b ─┤→ aggregate
      └─→ process_c ─┘

Execution Flow:
1. 'extract' runs first (fan-out point)
2. 'process_a', 'process_b', 'process_c' run in parallel
3. 'aggregate' runs only after ALL processing jobs complete (fan-in point)

Key Concepts:
- Parallel execution: Multiple jobs running simultaneously
- Synchronization: Fan-in point waits for all parallel jobs
- Scalability: Process large datasets by splitting work
- Load balancing: Distribute work across multiple workers
- Aggregation: Combine results from parallel processing

Real-world Use Cases:
- Batch processing (split large files into chunks, process in parallel)
- MapReduce patterns (map phase fans out, reduce phase fans in)
- Image processing (split image into tiles, process tiles in parallel)
- Scientific computing (parallel simulations with result aggregation)
- ETL pipelines (parallel transformation of different data partitions)

Queuack Features Demonstrated:
- Multiple dependencies with depends_on=[list]
- Parallel job execution
- Synchronization points
- Job naming and organization
- Execution level visualization

# Difficulty: intermediate
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("fanout")
queue = DuckQueue(db_path)

print("🦆 Fan-out/Fan-in DAG Example")
print("============================")
print("This example shows parallel processing with synchronization:")
print()
print("       extract")
print("      ├─→ process_a ─┐")
print("      ├─→ process_b ─┤→ aggregate")
print("      └─→ process_c ─┘")
print()
print("1. Extract runs first")
print("2. Three process jobs run in parallel")
print("3. Aggregate waits for all three to complete")
print()


def extract():
    print("📥 Extracting data...")
    return [1, 2, 3, 4, 5]


def process_partition(partition_id):
    print(f"⚙️ Processing partition {partition_id}")
    # Simulate processing different partitions
    partition_data = {0: [1, 2], 1: [3, 4], 2: [5, 6]}
    data = partition_data.get(partition_id, [])
    return sum(data)


def aggregate():
    print("📊 Aggregating all partition results...")
    # In a real system, this might read from a database or shared store
    return "Aggregation complete"


print("🔧 Building DAG...")
print("   - extract: single job")
print("   - process_0, process_1, process_2: parallel jobs")
print("   - aggregate: synchronization point")
print()

with queue.dag("fan_out_fan_in") as dag:
    extract_job = dag.enqueue(extract, name="extract")

    # Fan out: 3 parallel processes
    process_jobs = []
    for i in range(3):
        job = dag.enqueue(
            process_partition, args=(i,), name=f"process_{i}", depends_on="extract"
        )
        process_jobs.append(f"process_{i}")

    # Fan in: aggregate waits for all
    dag.enqueue(
        aggregate,
        name="aggregate",
        depends_on=process_jobs,  # Waits for all 3
    )

print("✓ Fan-out/fan-in DAG submitted")
print("Execution levels:", dag.get_execution_order())
print()

# Execute the DAG jobs
print("🚀 Executing DAG jobs...")
print("Watch for parallel processing of partitions!")
print()

# Execute the DAG jobs
print("\n🚀 Executing DAG jobs...")
import time

processed = 0
expected_jobs = 5  # extract + 3 process + 1 aggregate
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
