"""webhook_processor.py - Example webhook processing with retries

# Difficulty: intermediate
"""


import random
import asyncio
import os
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, WorkerPool, async_task




@async_task
async def process_webhook(payload: dict):
    """Pretend to process incoming webhook; fail sometimes to trigger retries."""
    print(f"Processing webhook for id={payload.get('id')}")
    # Randomly fail to exercise retry logic
    if random.random() < 0.4:
        print("Transient error while processing webhook - will raise to trigger retry")
        raise RuntimeError("transient error")

    # Simulate async work
    await asyncio.sleep(0.1)
    print("Processed webhook:", payload)
    return True



async def main():
    db = create_temp_path("webhooks_async")
    queue = DuckQueue(db)

    # Simulate receiving a few webhooks and enqueue them with retries
    for i in range(10):
        payload = {"id": f"wh-{i}", "body": f"payload-{i}"}
        job_id = queue.enqueue(
            process_webhook,
            args=(payload,),
            max_attempts=5,  # allow retries
            timeout_seconds=10,
            check_backpressure=True,
        )
        print(f"Enqueued webhook job {job_id[:8]}")

    print(f"DB path: {db}")
    print("\nDemo: Running async WorkerPool in-process. You can also run an external worker in another terminal.")

    # Start a WorkerPool in-process for demo (async jobs supported)
    pool = WorkerPool(queue, num_workers=2)
    pool.start()

    # Poll for progress

    while True:
        stats = queue.stats()
        print(f"Stats: {stats}")
        # Use 'claimed' instead of 'in_progress' (see queuack stats keys)
        if stats['pending'] == 0 and stats['claimed'] == 0:
            break
        await asyncio.sleep(0.1)

    pool.stop()
    print("All webhooks processed!")


if __name__ == "__main__":
    # Enable fast test/demo mode if available
    os.environ["QUEUACK_FAST_TESTS"] = "1"
    asyncio.run(main())

