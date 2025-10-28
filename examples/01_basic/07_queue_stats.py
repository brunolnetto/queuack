"""07_queue_stats.py - Monitor queue health and progress

# Difficulty: beginner
"""
import time
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

def slow_task(duration: float):
    """Simulates a slow task."""
    time.sleep(duration)
    return f"Completed after {duration}s"

db_path = create_temp_path("stats")
queue = DuckQueue(db_path)

# Enqueue various jobs
print("Enqueuing jobs...")
for i in range(5):
    queue.enqueue(slow_task, args=(0.1,))
queue.enqueue(slow_task, args=(0.1,), delay_seconds=5)

# Check stats
print("\nInitial stats:")
stats = queue.stats()
for status, count in stats.items():
    print(f"  {status}: {count}")

# Process one job
job = queue.claim()
if job:
    result = job.execute()
    queue.ack(job.id, result=result)

# Check updated stats
print("\nAfter processing one job:")
stats = queue.stats()
for status, count in stats.items():
    if count > 0:
        print(f"  {status}: {count}")

# Get specific job details
print(f"\nJob details:")
job_info = queue.get_job(job.id)
print(f"  ID: {job_info.id[:8]}")
print(f"  Status: {job_info.status}")
print(f"  Attempts: {job_info.attempts}/{job_info.max_attempts}")
print(f"  Created: {job_info.created_at}")
print(f"  Completed: {job_info.completed_at}")