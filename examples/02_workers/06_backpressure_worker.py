"""06_backpressure_worker.py - Worker that respects queue backpressure

This example demonstrates how workers can adapt to queue load:
- Monitor queue depth before enqueuing new work
- Slow down or pause when queue gets too full
- Handle BackpressureError gracefully
- Prevent memory exhaustion from unbounded queue growth

Key concepts:
- Backpressure: Mechanism to prevent queue overload
- Dynamic throttling: Adjust enqueue rate based on queue depth
- Producer/consumer balance: Ensure workers can keep up with producers

# Difficulty: intermediate
"""

import time
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, BackpressureError

def fast_producer(item: int):
    """Fast task that produces more work."""
    print(f"📦 Producing item {item}")
    return f"Produced {item}"

def slow_consumer(item: int):
    """Slow task that takes time to process."""
    print(f"⚙️ Consuming item {item}...")
    time.sleep(2)  # Simulate slow processing
    return f"Consumed {item}"

db_path = create_temp_path("backpressure")

# Set custom backpressure thresholds for this demo
class CustomQueue(DuckQueue):
    @classmethod
    def backpressure_warning_threshold(cls):
        return 5  # Warn at 5 pending jobs
    
    @classmethod
    def backpressure_block_threshold(cls):
        return 10  # Block at 10 pending jobs

queue = CustomQueue(db_path)

print("🦆 Backpressure Worker Example")
print("================================")
print("This example shows how to handle queue overload gracefully.")
print("Warning threshold: 5 jobs | Block threshold: 10 jobs")
print()

# Producer loop with backpressure handling
print("📤 Starting fast producer (will hit backpressure)...")
for i in range(20):
    try:
        queue.enqueue(
            slow_consumer,
            args=(i,),
            check_backpressure=True  # Enable backpressure checking
        )
        print(f"  ✓ Enqueued job {i}")
    except BackpressureError as e:
        print(f"  ⚠️  Backpressure hit at job {i}: {e}")
        print(f"  💤 Sleeping 5s to let workers catch up...")
        time.sleep(5)
        
        # Retry after backoff
        queue.enqueue(slow_consumer, args=(i,))
        print(f"  ✓ Enqueued job {i} after backoff")
    
    # Check stats periodically
    if i % 5 == 0:
        stats = queue.stats()
        pending = stats.get('pending', 0)
        print(f"  📊 Queue depth: {pending} pending jobs")

print()
print("📥 Starting consumer worker to process backlog...")

# Consumer worker
processed = 0
while processed < 20:
    job = queue.claim()
    if job:
        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            processed += 1
            print(f"✅ Processed {processed}/20 jobs")
        except Exception as e:
            queue.ack(job.id, error=str(e))
    else:
        time.sleep(0.5)

print("\n🎉 All jobs processed!")