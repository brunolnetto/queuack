"""Multi-threaded worker for parallel execution.

This example demonstrates concurrent job processing in Queuack:
- Enqueue multiple slow-running jobs
- Start a worker with multiple threads (concurrency=4)
- Jobs are processed in parallel, significantly reducing total execution time
- Compare this to single-threaded processing which would take much longer
- Worker automatically exits when all jobs are processed

Key concepts:
- Concurrency: Multiple threads processing jobs simultaneously
- Parallel execution: Faster completion for CPU-bound or I/O-bound tasks
- Worker threads: Each thread claims and processes jobs independently
- Scalability: Handle more work by increasing concurrency
- Auto-exit: Worker stops when queue is empty for several seconds

# Difficulty: intermediate
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker


def slow_task(task_id: int):
    """Simulate a slow task that takes 2 seconds."""
    print(f"🔄 Starting task {task_id}...")
    time.sleep(2)  # Simulate slow work
    print(f"✅ Completed task {task_id}")
    return f"Task {task_id} done"


# Create temporary database
db_path = create_temp_path("concurrent")
queue = DuckQueue(db_path)

print("🦆 Concurrent Workers Example")
print("============================")
print("This example shows parallel job processing with multiple worker threads.")
print("Each task takes 2 seconds. With 4 threads, total time should be ~10 seconds.")
print("(Sequential processing would take 40 seconds)")
print()

# Enqueue 20 tasks
print("📝 Enqueuing 20 slow tasks (2 seconds each)...")
for i in range(20):
    job_id = queue.enqueue(slow_task, args=(i,))
    print(f"  Enqueued job {job_id[:8]}: task-{i}")

print()
print("👷 Processing 20 tasks with 4 concurrent threads...")
print("Worker will exit automatically when all jobs are processed.")
print()

start = time.perf_counter()
worker = Worker(queue, concurrency=4)

processed = 0
empty_polls = 0
max_empty_polls = 3  # Exit after 3 seconds of no jobs

try:
    while empty_polls < max_empty_polls:
        job = queue.claim()
        if job:
            processed += 1
            empty_polls = 0  # Reset counter
            if processed == 1:
                print("📋 Jobs being processed in parallel...")
        else:
            empty_polls += 1
            if empty_polls == 1:
                print("⏳ Waiting for remaining jobs to complete...")
            time.sleep(1.0)

    duration = time.perf_counter() - start

    print()
    print(f"⏱️  Total execution time: {duration:.1f} seconds")
    print(f"📊 Processed {processed} jobs total")
    print(
        "💡 With 4 threads, we completed 20 tasks much faster than sequential processing!"
    )
    print("   (Sequential would have taken ~40 seconds)")

except KeyboardInterrupt:
    duration = time.perf_counter() - start
    print(f"\n🛑 Interrupted by user after {duration:.1f} seconds")
    print(f"Processed {processed} jobs before shutdown.")
