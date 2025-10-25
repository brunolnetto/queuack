"""Benchmark Queuack performance."""

import time
from concurrent.futures import ThreadPoolExecutor

from queuack import DuckQueue


def benchmark_enqueue(num_jobs=1000):
    """Benchmark enqueue throughput."""
    queue = DuckQueue(":memory:")

    start = time.perf_counter()
    for i in range(num_jobs):
        queue.enqueue(lambda x: x, args=(i,))
    duration = time.perf_counter() - start

    throughput = num_jobs / duration
    print(f"Enqueue: {throughput:.0f} jobs/sec")
    return throughput


def benchmark_claim_ack(num_jobs=1000):
    """Benchmark claim/ack throughput."""
    queue = DuckQueue(":memory:")

    # Setup
    for i in range(num_jobs):
        queue.enqueue(lambda x: x, args=(i,))

    # Benchmark
    start = time.perf_counter()
    for _ in range(num_jobs):
        job = queue.claim()
        if job:
            result = job.execute()
            queue.ack(job.id, result=result)
    duration = time.perf_counter() - start

    throughput = num_jobs / duration
    print(f"Claim+Ack: {throughput:.0f} jobs/sec")
    return throughput


def benchmark_concurrent(num_jobs=1000, concurrency=4):
    """Benchmark concurrent execution."""
    queue = DuckQueue(":memory:")

    # Enqueue
    for i in range(num_jobs):
        queue.enqueue(lambda x: time.sleep(0.01), args=(i,))

    # Process concurrently
    from queuack import Worker

    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for _ in range(concurrency):
            worker = Worker(queue, concurrency=1)
            future = executor.submit(worker.run, poll_interval=0.1)
            futures.append(future)

    duration = time.perf_counter() - start
    print(f"Concurrent ({concurrency} workers): {num_jobs / duration:.0f} jobs/sec")


if __name__ == "__main__":
    print("Queuack Benchmarks")
    print("=" * 50)
    benchmark_enqueue(1000)
    benchmark_claim_ack(1000)
    benchmark_concurrent(1000, concurrency=4)
