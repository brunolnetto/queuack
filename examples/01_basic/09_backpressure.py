"""09_backpressure.py - Demonstrate BackpressureError and check_backpressure

# Difficulty: beginner
"""

import time

from examples.utils.tempfile import create_temp_path
from queuack import BackpressureError, DuckQueue


def tiny_task(i: int):
    print(f"🔁 executing tiny task {i}")
    """09_backpressure.py - Demonstrate BackpressureError and check_backpressure

    # Difficulty: beginner
    """

    import time

    from examples.utils.tempfile import create_temp_path
    from queuack import BackpressureError, DuckQueue


    def tiny_task(i: int):
        print(f"🔁 executing tiny task {i}")
        time.sleep(0.01)
        return i


    if __name__ == "__main__":
        db = create_temp_path("backpressure")
        queue = DuckQueue(db)

        print("Enqueuing until we hit backpressure (check_backpressure=True)")

        enqueued = 0
        try:
            # Keep enqueuing quickly; the queue will eventually raise BackpressureError
            for i in range(100000):
                queue.enqueue(tiny_task, args=(i,), check_backpressure=True)
                enqueued += 1
                if enqueued % 100 == 0:
                    print(f"-> enqueued {enqueued} jobs")
        except BackpressureError as e:
            print(f"⚠️  BackpressureError raised after {enqueued} jobs: {e}")

        print("Now claim and process a few jobs to relieve pressure")
        for _ in range(10):
            job = queue.claim()
            if not job:
                break
            res = job.execute()
            queue.ack(job.id, result=res)
            print(f" processed job {job.id[:8]} -> {res}")

        print("Final stats:", queue.stats())
