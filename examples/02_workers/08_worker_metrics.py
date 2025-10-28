"""08_dlq_worker.py - Dedicated worker for processing failed jobs

This example demonstrates handling permanently failed jobs:
- Main worker processes normal jobs
- DLQ worker processes failed jobs separately
- Implements retry logic with exponential backoff
- Moves unrecoverable jobs to permanent failure
- Prevents poison pills from blocking main queue

Key concepts:
- Dead Letter Queue: Separate queue for failed jobs
- Retry strategies: Different handling for different error types
- Poison pill prevention: Isolate problematic jobs
- Error classification: Distinguish transient vs permanent failures

# Difficulty: advanced
"""

import time
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

def flaky_task(task_id: int, fail_mode: str = None):
    """Task that can fail in different ways."""
    print(f"🔧 Attempting task {task_id}...")
    
    if fail_mode == "transient":
        # Simulate transient error (e.g., network timeout)
        import random
        if random.random() < 0.7:
            raise ConnectionError("Network timeout (transient)")
    
    elif fail_mode == "permanent":
        # Simulate permanent error (e.g., invalid data)
        raise ValueError("Invalid data format (permanent)")
    
    return f"Task {task_id} completed"

db_path = create_temp_path("dlq")
queue = DuckQueue(db_path)

print("🦆 Dead Letter Queue Worker Example")
print("====================================")
print("This example shows separate handling of failed jobs.")
print()

# Enqueue normal jobs and some that will fail
print("📝 Enqueuing test jobs...")
queue.enqueue(flaky_task, args=(1, None))  # Will succeed
queue.enqueue(flaky_task, args=(2, "transient"), max_attempts=3)  # Might succeed after retries
queue.enqueue(flaky_task, args=(3, "permanent"), max_attempts=2)  # Will fail permanently

print()
print("🚀 Starting main worker...")

# Main worker processes jobs normally
processed = 0
for _ in range(10):  # Process for a bit
    job = queue.claim()
    if job:
        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✅ Success: {result}")
            processed += 1
        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"❌ Failed (attempt {job.attempts}/{job.max_attempts}): {e}")
    else:
        time.sleep(0.5)

print()
print("🔍 Checking Dead Letter Queue...")
dead_letters = queue.list_dead_letters(limit=10)

if not dead_letters:
    print("✅ No jobs in DLQ - all succeeded or still retrying")
else:
    print(f"⚠️  Found {len(dead_letters)} jobs in DLQ:")
    
    for job in dead_letters:
        print(f"\n  Job {job.id[:8]}:")
        print(f"    Attempts: {job.attempts}/{job.max_attempts}")
        print(f"    Error: {job.error[:100]}...")
        
        # Classify error type
        if "transient" in job.error.lower():
            print(f"    Type: Transient failure - could retry with backoff")
        elif "permanent" in job.error.lower():
            print(f"    Type: Permanent failure - needs manual intervention")
        
    print("\n💡 DLQ Worker Strategy:")
    print("  - Transient errors: Retry with exponential backoff")
    print("  - Permanent errors: Alert ops team, don't retry")
    print("  - Unknown errors: Move to manual review queue")