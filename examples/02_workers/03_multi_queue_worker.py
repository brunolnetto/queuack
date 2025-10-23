"""Worker listening to multiple queues with priorities.

This example demonstrates priority-based queue processing:
- Create multiple named queues with different priorities
- Enqueue jobs to specific queues
- Worker processes queues in priority order (highest first)
- Lower priority queues are processed only when higher ones are empty
- Worker automatically exits when all queues are empty

Key concepts:
- Named queues: Jobs can be routed to specific queues
- Queue priorities: Higher priority queues are processed first
- Worker queue list: Worker listens to multiple queues simultaneously
- Priority scheduling: Critical jobs get processed before background jobs
- Auto-exit: Worker stops when all queues are empty for several seconds

# Difficulty: intermediate
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker

db_path = create_temp_path("multi")
queue = DuckQueue(db_path)


def process_queue_task(queue_name: str) -> None:
    """Process a task from a specific queue."""
    print(f"📋 Processing task from '{queue_name}' queue")


# Define queues with priorities (higher number = higher priority)
queue_attrs = [
    ("critical", 100),  # Highest priority - emergency tasks
    ("default", 50),  # Normal priority - regular work
    ("background", 10),  # Lowest priority - maintenance/cleanup
]

print("🦆 Multi-Queue Worker Example")
print("============================")
print("This example shows priority-based processing across multiple queues.")
print("Jobs in higher priority queues are processed before lower priority ones.")
print()

# Enqueue one job to each queue
print("📝 Enqueuing one job to each priority queue...")
for name, priority in queue_attrs:
    job_id = queue.enqueue(process_queue_task, args=(name,), queue=name)
    print(f"  📋 Enqueued to '{name}' queue (priority {priority}): job {job_id[:8]}")

print()
print("👷 Starting worker that processes all queues by priority...")
print("Expected order: critical → default → background")
print("Worker will exit automatically when all jobs are processed.")
print()

# Worker processes queues by priority
worker = Worker(queue, queues=queue_attrs)

processed = 0
empty_polls = 0
max_empty_polls = 3  # Exit after 3 seconds of no jobs

try:
    while empty_polls < max_empty_polls:
        job = None
        # Try to claim from queues in priority order
        for queue_name, _ in queue_attrs:
            job = queue.claim(queue=queue_name)
            if job:
                break

        if job:
            processed += 1
            empty_polls = 0  # Reset counter
            print(
                f"📋 Processing job #{processed}: {job.id[:8]} from '{job.queue}' queue"
            )

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
                print("⏳ No jobs available in any queue, waiting...")
            time.sleep(1.0)

    print(f"\n🎉 Worker finished! Processed {processed} jobs total from all queues.")

except KeyboardInterrupt:
    print("\n🛑 Interrupted by user")
    print(f"Processed {processed} jobs before shutdown.")
