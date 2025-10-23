"""Basic enqueue/claim/ack pattern.

# Difficulty: beginner
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue


def send_email(to: str, subject: str, body: str):
    """Simulate sending an email."""
    print(f"📧 Sending to {to}: {subject}")
    time.sleep(0.5)
    return f"Email sent to {to}"


# Producer
db_path = create_temp_path("basic")
queue = DuckQueue(db_path)

job_id = queue.enqueue(
    send_email,
    args=("user@example.com", "Hello", "Welcome!"),
)
print(f"Enqueued job: {job_id}")

# Consumer
job = queue.claim()
if job:
    result = job.execute()
    queue.ack(job.id, result=result)
    print(f"Result: {result}")
