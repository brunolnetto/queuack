"""health_checks.py - Demonstrate simple worker health monitoring

# Difficulty: intermediate
"""

import threading
import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, WorkerPool


def work(item: int):
    print(f"✅ processing {item}")
    time.sleep(0.1)
    return item


def monitor(pool: WorkerPool, queue: DuckQueue, interval: float = 1.0):
    """Simple monitor that checks thread liveness and queue progress."""
    last_done = 0
    while True:
        # Check threads
        alive = all(t.is_alive() for t in pool.threads)
        stats = queue.stats()
        done = stats.get("done", 0)

        print(f"[monitor] threads_alive={alive}, stats={stats}")

        # If no progress for a while, emit warning
        if done == last_done:
            print("[monitor] No new completed jobs since last check")
        last_done = done

        if not alive:
            print("[monitor] One or more worker threads died — consider restarting pool")
            break

        time.sleep(interval)


if __name__ == "__main__":
    db = create_temp_path("worker_health")
    queue = DuckQueue(db)

    # Enqueue a bunch of quick tasks
    for i in range(50):
        queue.enqueue(work, args=(i,))

    # Start a WorkerPool (background threads)
    pool = WorkerPool(queue, num_workers=3, concurrency=2)
    pool.start()

    # Start monitor in main thread (or its own thread)
    try:
        monitor(pool, queue, interval=2.0)
    except KeyboardInterrupt:
        print("Stopping monitor")
    finally:
        pool.stop()
