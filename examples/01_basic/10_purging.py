"""10_purging.py - Demonstrate queue.purge() for cleanup

# Difficulty: beginner
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue


def quick_task(i: int):
    print(f"🏷️  quick task {i}")
    return i


if __name__ == "__main__":
    db = create_temp_path("purge_example")
    queue = DuckQueue(db)

    # Enqueue a few jobs and process them so they become 'done'
    ids = []
    for i in range(5):
        jid = queue.enqueue(quick_task, args=(i,))
        ids.append(jid)

    print("Enqueued jobs:", ids)

    # Claim and ack all jobs
    while True:
        job = queue.claim()
        if not job:
            break
        result = job.execute()
        queue.ack(job.id, result=result)

    print("Stats before purge:", queue.stats())

    # Purge 'done' jobs older than 0 hours (immediate)
    purged = queue.purge(status="done", older_than_hours=0)
    print(f"Purged {purged} done jobs")

    print("Stats after purge:", queue.stats())

