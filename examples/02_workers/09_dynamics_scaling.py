"""09_dynamic_scaling.py - Adjust worker count based on queue depth

This example demonstrates auto-scaling workers:
- Monitor queue depth in real-time
- Add workers when queue grows
- Remove workers when queue shrinks
- Prevent resource exhaustion
- Optimize processing speed vs resource usage

Key concepts:
- Auto-scaling: Dynamic resource allocation
- Queue depth monitoring: Track pending job count
- Worker lifecycle: Start/stop workers dynamically
- Resource optimization: Use only what's needed

# Difficulty: advanced
"""

import time
import threading
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, WorkerPool

def work_item(item: int):
    """Simple work item."""
    print(f"⚙️ Processing item {item}")
    time.sleep(1)
    return f"Processed {item}"

db_path = create_temp_path("scaling")
queue = DuckQueue(db_path)

print("🦆 Dynamic Worker Scaling Example")
print("==================================")
print("This example shows auto-scaling workers based on queue depth.")
print()

# Scaling parameters
MIN_WORKERS = 1
MAX_WORKERS = 5
SCALE_UP_THRESHOLD = 10    # Add worker if >10 pending jobs
SCALE_DOWN_THRESHOLD = 2   # Remove worker if <2 pending jobs

class ScalingWorkerPool:
    """Worker pool that scales based on queue depth."""
    
    def __init__(self, queue, min_workers=1, max_workers=5):
        self.queue = queue
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.pools = []
        self.running = False
        
        # Start with minimum workers
        self._add_workers(min_workers)
    
    def _add_workers(self, count):
        """Add worker pools."""
        for _ in range(count):
            if len(self.pools) < self.max_workers:
                pool = WorkerPool(self.queue, num_workers=1, concurrency=1)
                pool.start()
                self.pools.append(pool)
                print(f"📈 Scaled UP to {len(self.pools)} workers")
    
    def _remove_workers(self, count):
        """Remove worker pools."""
        for _ in range(count):
            if len(self.pools) > self.min_workers:
                pool = self.pools.pop()
                pool.stop(timeout=5)
                print(f"📉 Scaled DOWN to {len(self.pools)} workers")
    
    def monitor_and_scale(self, interval=2.0):
        """Monitor queue and scale workers."""
        self.running = True
        
        while self.running:
            stats = self.queue.stats()
            pending = stats.get('pending', 0) + stats.get('claimed', 0)
            
            print(f"📊 Queue depth: {pending} jobs | Workers: {len(self.pools)}")
            
            # Scale up if queue is growing
            if pending > SCALE_UP_THRESHOLD and len(self.pools) < self.max_workers:
                self._add_workers(1)
            
            # Scale down if queue is shrinking
            elif pending < SCALE_DOWN_THRESHOLD and len(self.pools) > self.min_workers:
                self._remove_workers(1)
            
            time.sleep(interval)
    
    def stop(self):
        """Stop all workers."""
        self.running = False
        for pool in self.pools:
            pool.stop(timeout=5)
        print("🛑 All workers stopped")

# Enqueue initial batch
print("📝 Enqueuing initial batch (5 jobs)...")
for i in range(5):
    queue.enqueue(work_item, args=(i,))

# Start scaling pool
pool = ScalingWorkerPool(queue, min_workers=MIN_WORKERS, max_workers=MAX_WORKERS)

# Monitor in background thread
monitor_thread = threading.Thread(target=pool.monitor_and_scale, daemon=True)
monitor_thread.start()

try:
    # Simulate varying load
    print("\n🔄 Simulating varying load...\n")
    
    # Burst of work (should scale up)
    print("📤 Burst: Enqueuing 20 jobs...")
    for i in range(5, 25):
        queue.enqueue(work_item, args=(i,))
    
    time.sleep(10)
    
    # Trickle of work (should scale down)
    print("\n💧 Trickle: Enqueuing 3 jobs slowly...")
    for i in range(25, 28):
        queue.enqueue(work_item, args=(i,))
        time.sleep(5)
    
    time.sleep(10)
    
except KeyboardInterrupt:
    print("\n⚠️  Interrupted by user")

finally:
    pool.stop()
    print("✅ Shutdown complete")