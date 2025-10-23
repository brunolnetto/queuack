"""Multiple worker processes simulating distributed deployment.

# Difficulty: advanced
"""

import multiprocessing
import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker


def shared_task(task_id: int):
    """Shared task that can be processed by any worker."""
    print(f"[Shared] Processing task {task_id}")
    time.sleep(0.3)
    return f"Shared task {task_id} completed"


def worker_job_handler(worker_id: str, job_num: int):
    """Job handler for individual workers."""
    print(f"[Worker {worker_id}] Processing job #{job_num}")
    time.sleep(0.5)  # Simulate work
    return f"Job completed by {worker_id}"


def simulate_distributed_worker(worker_id: str, db_path: str):
    """Simulate a worker on a different 'machine'."""
    print(f"[Worker {worker_id}] Starting on 'machine' {worker_id}")

    # Create queue connection
    queue = DuckQueue(db_path)

    # Create worker with unique ID
    worker = Worker(
        queue,
        worker_id=worker_id,
        concurrency=2,  # Each worker handles 2 concurrent jobs
    )

    # Process jobs for a limited time
    start_time = time.time()
    jobs_processed = 0

    # Enqueue some work for this worker
    for i in range(3):
        queue.enqueue(
            worker_job_handler,
            args=(worker_id, i + 1),
            priority=i % 3,  # Mix priorities
        )

    print(f"[Worker {worker_id}] Enqueued 3 jobs, starting worker...")

    # Start worker in a separate thread so we can stop it after a timeout
    import threading

    worker_thread = threading.Thread(target=worker.run, args=(0.1,))
    worker_thread.start()

    # Let worker run for a limited time
    time.sleep(3)

    # Stop the worker
    worker.should_stop = True
    worker_thread.join(timeout=1)

    print(f"[Worker {worker_id}] Worker stopped")


def main():
    """Demonstrate distributed workers across multiple 'machines'."""
    print("🚀 Distributed Workers Demo")
    print("=" * 50)

    # Use local database (simulating shared storage)
    db_path = create_temp_path("distributed")
    print(f"Using shared database: {db_path}")

    # Create initial queue and add some jobs
    queue = DuckQueue(db_path)

    # Add initial jobs that any worker can process
    print("\n📝 Enqueuing shared jobs...")
    for i in range(5):
        queue.enqueue(shared_task, args=(i,), priority=i % 3)

    print("✅ Enqueued 5 shared jobs")

    # Simulate 3 workers on different "machines"
    print("\n🏭 Starting 3 distributed workers...")

    workers = []
    machine_names = ["web-server-01", "worker-node-02", "batch-server-03"]

    # Start workers in separate processes
    for machine in machine_names:
        p = multiprocessing.Process(
            target=simulate_distributed_worker, args=(machine, db_path)
        )
        workers.append(p)
        p.start()
        time.sleep(0.1)  # Stagger startup

    # Wait for all workers to complete
    print("\n⏳ Waiting for workers to complete processing...")
    for p in workers:
        p.join()

    print("\n📊 Final queue status:")
    # Check remaining jobs
    stats = queue.stats()
    remaining = stats.get("pending", 0) + stats.get("delayed", 0)
    print(f"Jobs remaining in queue: {remaining}")
    print(f"Jobs completed: {stats.get('done', 0)}")
    print(f"Jobs failed: {stats.get('failed', 0)}")

    print("\n✅ Distributed workers demo completed!")
    print("Each worker processed jobs concurrently, demonstrating")
    print("how Queuack enables distributed processing across multiple machines.")


if __name__ == "__main__":
    main()
