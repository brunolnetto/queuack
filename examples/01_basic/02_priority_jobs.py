"""Demonstrate priority-based job ordering.

# Difficulty: beginner
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("priority")
queue = DuckQueue(db_path)


def print_priority(priority: str) -> None:
    """Module-level function to print a priority label.

    Using a top-level function and passing the label as an argument
    ensures the callable is picklable across processes.
    """
    print(f"{priority} priority.")


# Enqueue jobs with different priorities
priority_list = [("low", 10), ("Medium", 50), ("HIGH", 90)]

for name, level in priority_list:
    # Enqueue a top-level function with the priority passed as an arg
    queue.enqueue(print_priority, args=(name,), priority=level)

# Workers claim highest priority first
for _ in range(3):
    job = queue.claim()
    if job:
        job.execute()
        queue.ack(job.id)
