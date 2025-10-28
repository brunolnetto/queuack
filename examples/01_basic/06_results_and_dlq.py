"""06_results_and_dlq.py - Retrieve results and handle permanent failures

# Difficulty: beginner
"""
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

def calculate(x: int, y: int) -> int:
    """Returns sum of two numbers."""
    return x + y

def always_fails():
    """Job that always fails for DLQ demo."""
    raise ValueError("This job is designed to fail")

db_path = create_temp_path("results")
queue = DuckQueue(db_path)

# 1. Successful job with result
print("=== Successful Job ===")
job_id = queue.enqueue(calculate, args=(10, 20))

job = queue.claim()
result = job.execute()
queue.ack(job.id, result=result)

# Retrieve result later
retrieved_result = queue.get_result(job_id)
print(f"Retrieved result: {retrieved_result}")  # 30

# 2. Failed job (moves to Dead Letter Queue)
print("\n=== Failed Job (DLQ) ===")
failed_id = queue.enqueue(always_fails, max_attempts=2)

# Try to process (will fail)
for _ in range(2):
    job = queue.claim()
    if job:
        try:
            job.execute()
            queue.ack(job.id)
        except Exception as e:
            queue.ack(job.id, error=str(e))

# Check Dead Letter Queue
print("\nDead Letter Queue:")
dead_letters = queue.list_dead_letters(limit=10)
for job in dead_letters:
    print(f"  Job {job.id[:8]}: {job.error[:50]}...")