"""Efficiently enqueue multiple jobs at once.

# Difficulty: beginner
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue


def process_user(user_id: int):
    print(f"Processing user {user_id}")
    return f"User {user_id} processed"


db_path = create_temp_path("batch")
queue = DuckQueue(db_path)

# Batch enqueue 1000 jobs in one transaction
jobs = [(process_user, (i,), {}) for i in range(10)]
job_ids = queue.enqueue_batch(jobs)

print(f"Enqueued {len(job_ids)} jobs")
print(queue.stats())  # {'pending': 10, ...}
