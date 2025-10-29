"""
batch_email_sender.py - Send emails in batches with simple rate limiting.
Difficulty: intermediate.
"""

import asyncio
import os
from typing import List
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, WorkerPool, async_task

@async_task
async def send_email_batch(batch: List[str]):
    print(f"Sending batch of {len(batch)} emails: {batch}")
    # Simulate async external API call
    await asyncio.sleep(0.2)
    return len(batch)

def demo_parallel_dag(queue: DuckQueue, recipients: list, batch_size: int = 10):
    """Build and execute a parallel DAG using DAG context manager and slicing."""
    with queue.dag("batch_email_parallel") as dag_ctx:
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i : i + batch_size]
            dag_ctx.enqueue(send_email_batch, args=(batch,), name=f"batch_{i//batch_size+1}")
        run_id = dag_ctx.submit()

    # dag_ctx.jobs maps node names to job IDs
    num_batches = len(dag_ctx.jobs)
    print(f"Submitted parallel DAG with {num_batches} batches.")

    # Return a DAGRun helper for polling
    from queuack import DAGRun

    return DAGRun(queue, run_id)

async def main():
    # Create fake recipients
    recipients = [f"user{i}@example.com" for i in range(35)]

    db = create_temp_path("batch_email_async")
    queue = DuckQueue(db)

    print(f"DB path: {db}")
    print("\nDemo: Running async WorkerPool in-process. You can also run an external worker in another terminal.")

    pool = WorkerPool(queue, num_workers=2)
    pool.start()

    dag_run = demo_parallel_dag(queue, recipients, batch_size=8)
    # Poll DAG run progress
    while True:
        progress = dag_run.get_progress()
        print(f"DAG progress: {progress}")
        if progress['pending'] == 0 and progress['claimed'] == 0:
            break
        await asyncio.sleep(0.1)

    pool.stop()
    print("All batches processed!")


if __name__ == "__main__":
    # Set parallel=True for DAG, False for sequential
    asyncio.run(main())
