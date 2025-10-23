"""Long-running worker process.

This example demonstrates the basic worker pattern in Queuack:
- Enqueue multiple jobs to a queue
- Start a single worker process that continuously processes jobs
- The worker runs in a loop, claiming and executing jobs one by one
- Worker automatically exits when all jobs are processed (no timeout needed)

Key concepts:
- Worker: A process that continuously polls for and executes jobs
- Claim/Ack: Worker claims a job (marks it as being processed) then acks it when done
- Sequential processing: Single worker processes jobs one at a time
- Auto-exit: Worker stops when queue is empty for several seconds

# Difficulty: beginner
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker


def process_task(data):
    """Simulate processing a task with some output."""
    print(f"Processing: {data}")
    return f"Processed {data}"


# Create a temporary database for this example
db_path = create_temp_path("worker")
queue = DuckQueue(db_path)

print("🦆 Single Worker Example")
print("========================")
print("This example shows a basic worker that processes jobs sequentially.")
print()

# Enqueue some test jobs
print("📝 Enqueuing 10 test jobs...")
for i in range(10):
    job_id = queue.enqueue(process_task, args=(f"task-{i}",))
    print(f"  Enqueued job {job_id[:8]}: task-{i}")

print()
print("👷 Starting worker (single thread, sequential processing)...")
print("Press Ctrl+C to stop the worker.")
print()

# Start worker
worker = Worker(queue)
print("👷 Starting worker (single thread, sequential processing)...")
print("Worker will exit automatically when all jobs are processed.")
print()

processed = 0
empty_polls = 0
max_empty_polls = 3  # Exit after 3 seconds of no jobs

try:
    while empty_polls < max_empty_polls:
        job = queue.claim()
        if job:
            processed += 1
            empty_polls = 0  # Reset counter
            print(f"📋 Processing job #{processed}: {job.id[:8]}")

            try:
                result = job.execute()
                queue.ack(job.id, result=result)
                print(f"✅ Completed job #{processed}")
            except Exception as e:
                queue.ack(job.id, error=str(e))
                print(f"❌ Failed job #{processed}: {e}")
        else:
            empty_polls += 1
            if empty_polls == 1:
                print("⏳ No jobs available, waiting...")
            time.sleep(1.0)

    print(f"\n🎉 Worker finished! Processed {processed} jobs total.")

except KeyboardInterrupt:
    print("\n🛑 Interrupted by user")
    print(f"Processed {processed} jobs before shutdown.")
