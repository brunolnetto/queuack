"""Handle shutdown signals properly.

This example demonstrates graceful shutdown handling in Queuack workers:
- Worker processes long-running jobs (5 seconds each)
- Signal handlers catch SIGTERM/SIGINT (Ctrl+C)
- Worker finishes current jobs before shutting down
- Tracks active jobs to prevent data loss during shutdown

Key concepts:
- Signal handling: Catch system signals for clean shutdown
- Graceful shutdown: Finish current work before stopping
- Active job tracking: Know which jobs are in progress
- No job loss: Ensure running jobs complete even during shutdown

# Difficulty: intermediate
"""

import signal
import threading
import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("shutdown")
queue = DuckQueue(db_path)

# Track active jobs for graceful shutdown
active_jobs = set()
shutdown_requested = threading.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals (SIGTERM, SIGINT)."""
    print("\n🛑 Shutdown requested! Finishing active jobs before exit...")
    shutdown_requested.set()


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def long_running_task(task_id):
    """Simulate a long-running task that takes 5 seconds."""
    print(f"🔄 Starting long task {task_id} (will take 5 seconds)...")
    time.sleep(5)
    result = f"Task {task_id} completed"
    print(f"✅ {result}")
    return result


print("🦆 Graceful Shutdown Example")
print("===========================")
print("This example shows how workers handle shutdown signals gracefully.")
print("Each job takes 5 seconds. Try pressing Ctrl+C during execution.")
print("The worker will finish current jobs before shutting down.")
print()

# Enqueue a couple of long-running jobs
print("📝 Enqueuing 2 long-running jobs (5 seconds each)...")
for i in range(2):
    job_id = queue.enqueue(long_running_task, args=(i,))
    print(f"  Enqueued job {job_id[:8]}: task-{i}")

print()
print("👷 Starting worker with graceful shutdown handling...")
print("Press Ctrl+C to request shutdown (worker will finish active jobs first)")
print()

# Worker loop with graceful shutdown
while not shutdown_requested.is_set():
    job = queue.claim()
    if job:
        active_jobs.add(job.id)
        try:
            result = job.execute()
            print(f"📋 Task result: {result}")
            queue.ack(job.id, result=result)
        finally:
            active_jobs.remove(job.id)
    else:
        # No jobs available, wait a bit
        time.sleep(1)

print(f"✅ Shutdown complete. {len(active_jobs)} jobs were still active.")
