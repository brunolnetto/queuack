"""05_error_handling.py - Handle failures and retries

# Difficulty: beginner
"""
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

def flaky_api_call(attempt_num: int):
    """Simulates a flaky API that fails first 2 times."""
    print(f"Attempt {attempt_num}")
    if attempt_num < 3:
        raise Exception(f"API error on attempt {attempt_num}")
    return "Success!"

db_path = create_temp_path("errors")
queue = DuckQueue(db_path)

# Job will retry up to 3 times automatically
job_id = queue.enqueue(
    flaky_api_call,
    args=(1,),
    max_attempts=3,
    timeout_seconds=10
)

# Process with error handling
for attempt in range(3):
    job = queue.claim()
    if job:
        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✓ Success: {result}")
            break
        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"✗ Attempt {job.attempts}/{job.max_attempts} failed: {e}")

# Check final status
final_job = queue.get_job(job_id)
print(f"Final status: {final_job.status}")
if final_job.error:
    print(f"Error: {final_job.error}")