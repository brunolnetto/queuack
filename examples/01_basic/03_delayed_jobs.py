"""Verbose delayed jobs example.

This example shows how to schedule jobs to run in the future using
the `delay_seconds` argument. It enqueues multiple delayed jobs with
different delays, prints human-friendly messages with timestamps, and
runs a simple worker loop that polls for ready jobs.

The example uses `examples.utils.tempfile.create_temp_path` so each run
gets its own temporary DuckDB file and doesn't interfere with other
example runs.

# Difficulty: beginner
"""

import time
from datetime import datetime

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def delayed_print(msg: str) -> None:
    """Simple job function that prints a timestamped message."""
    print(f"{now_str()} - {msg}")


def schedule_demo():
    db_path = create_temp_path("delayed")
    queue = DuckQueue(db_path)

    jobs = [
        ("Short delay (3s)", 3),
        ("Medium delay (5s)", 5),
        ("Long delay (8s)", 8),
    ]

    print(f"{now_str()} - Enqueuing {len(jobs)} delayed jobs to DB: {db_path}")
    for label, delay in jobs:
        job_id = queue.enqueue(delayed_print, args=(label,), delay_seconds=delay)
        print(f"{now_str()} - Enqueued job {job_id[:8]}: '{label}' (delay={delay}s)")

    print(f"{now_str()} - Worker starting; polling for ready jobs...\n")

    # Worker loop: claim jobs as they become ready and execute them. We exit
    # once we've processed all enqueued jobs.
    processed = 0
    total = len(jobs)
    try:
        while processed < total:
            job = queue.claim()
            if job:
                print(
                    f"{now_str()} - Claimed job {job.id[:8]} (priority={job.priority})"
                )
                job.execute()
                queue.ack(job.id)
                processed += 1
            else:
                # No ready job yet — sleep briefly and try again
                time.sleep(0.8)
    except KeyboardInterrupt:
        print("\nWorker interrupted — exiting")


if __name__ == "__main__":
    schedule_demo()
