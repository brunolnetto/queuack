"""Custom backpressure thresholds with realistic job processing scenarios.

This example demonstrates how to implement custom backpressure policies for different
workload patterns. It shows adaptive thresholds, different backpressure strategies,
and how to handle queue overload gracefully.

# Difficulty: advanced

Key Concepts:
- Backpressure thresholds: warning vs blocking levels
- Adaptive policies: dynamic threshold adjustment based on system load
- Graceful degradation: different strategies for handling overload
- Load shedding: dropping low-priority jobs during high load
"""

import random
import threading
import time
from typing import List

from examples.utils.tempfile import create_temp_path
from queuack import BackpressureError, DuckQueue


class AdaptiveBackpressureQueue(DuckQueue):
    """Queue with adaptive backpressure based on system load and job types."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.system_load = 0.0
        self.load_history: List[float] = []
        self._load_lock = threading.Lock()

    @classmethod
    def backpressure_warning_threshold(cls):
        return 20  # Warn at 20 jobs

    @classmethod
    def backpressure_block_threshold(cls):
        return 100  # Block at 100 jobs

    def update_system_load(self, load: float):
        """Update system load measurement."""
        with self._load_lock:
            self.system_load = load
            self.load_history.append(load)
            # Keep only last 10 measurements
            if len(self.load_history) > 10:
                self.load_history.pop(0)

    def get_average_load(self) -> float:
        """Get average system load over recent history."""
        with self._load_lock:
            return (
                sum(self.load_history) / len(self.load_history)
                if self.load_history
                else 0.0
            )

    def should_apply_backpressure(self, job_priority: str = "normal") -> bool:
        """Determine if backpressure should be applied based on load and priority."""
        pending_count = self.stats()["pending"]
        avg_load = self.get_average_load()

        # Higher priority jobs get more lenient thresholds
        if job_priority == "high":
            return pending_count > 150 or avg_load > 0.9
        elif job_priority == "low":
            return pending_count > 50 or avg_load > 0.7
        else:  # normal
            return (
                pending_count > self.backpressure_warning_threshold() or avg_load > 0.8
            )


class PriorityBackpressureQueue(DuckQueue):
    """Queue that implements load shedding for low-priority jobs."""

    @classmethod
    def backpressure_warning_threshold(cls):
        return 15

    @classmethod
    def backpressure_block_threshold(cls):
        return 75

    def enqueue_with_priority(self, func, priority: str = "normal", **kwargs):
        """Enqueue job with priority-based backpressure."""
        if priority == "low" and self.should_shed_low_priority():
            print("🗑️  Shedding low-priority job due to high load")
            return None

        return self.enqueue(func, **kwargs)

    def should_shed_low_priority(self) -> bool:
        """Check if low-priority jobs should be shed."""
        stats = self.stats()
        return (
            stats["pending"] > 50
            or (stats["claimed"] / max(stats["pending"] + stats["claimed"], 1)) > 0.8
        )


def simulate_system_load(queue: AdaptiveBackpressureQueue):
    """Simulate varying system load."""
    while True:
        # Simulate realistic load patterns (peaks during business hours)
        hour = time.localtime().tm_hour
        base_load = 0.3 + 0.4 * (1 + random.uniform(-0.3, 0.3))  # Base load with noise

        # Business hours have higher load
        if 9 <= hour <= 17:
            load_multiplier = 1.5
        elif 18 <= hour <= 22:
            load_multiplier = 1.2
        else:
            load_multiplier = 0.6

        current_load = min(1.0, base_load * load_multiplier)
        queue.update_system_load(current_load)

        time.sleep(2)  # Update load every 2 seconds


def high_priority_task(task_id: int):
    """Critical business task that should rarely be blocked."""
    print(f"🚨 Processing high-priority task #{task_id}")
    time.sleep(random.uniform(0.5, 2.0))
    return f"High-priority task {task_id} completed"


def normal_priority_task(task_id: int):
    """Regular business task."""
    print(f"⚙️  Processing normal task #{task_id}")
    time.sleep(random.uniform(1.0, 3.0))
    return f"Normal task {task_id} completed"


def low_priority_task(task_id: int):
    """Background maintenance task that can be shed."""
    print(f"🧹 Processing low-priority cleanup #{task_id}")
    time.sleep(random.uniform(2.0, 5.0))
    return f"Cleanup task {task_id} completed"


def dummy_task(task_id: int):
    """Dummy task for overload testing."""
    print(f"📦 Processing dummy task #{task_id}")
    time.sleep(0.1)
    return f"Dummy task {task_id} completed"


def batch_enqueue_with_backpressure(
    queue: AdaptiveBackpressureQueue, priority_queue: PriorityBackpressureQueue
):
    """Demonstrate different backpressure scenarios."""
    print("🎯 Testing Adaptive Backpressure Queue:")
    print("=" * 50)

    # Test 1: Normal load
    print("\n📊 Phase 1: Normal load scenario")
    for i in range(10):
        try:
            queue.enqueue(normal_priority_task, args=(i,), check_backpressure=True)
            print(f"✅ Enqueued normal task {i}")
        except BackpressureError as e:
            print(f"⚠️  Backpressure blocked task {i}: {e}")
        time.sleep(0.1)

    # Test 2: High priority jobs during load
    print("\n🚨 Phase 2: High priority jobs (should bypass some backpressure)")
    for i in range(5):
        try:
            queue.enqueue(high_priority_task, args=(i,), check_backpressure=True)
            print(f"✅ Enqueued high-priority task {i}")
        except BackpressureError as e:
            print(f"⚠️  Backpressure blocked high-priority task {i}: {e}")
        time.sleep(0.1)

    print("\n🗑️  Phase 3: Load shedding for low-priority jobs")
    for i in range(20):
        result = priority_queue.enqueue_with_priority(
            low_priority_task, priority="low", args=(i,)
        )
        if result:
            print(f"✅ Enqueued low-priority task {i}")
        else:
            print(f"🗑️  Shed low-priority task {i} due to load")
        time.sleep(0.05)

    # Test 3: Extreme overload
    print("\n💥 Phase 4: Extreme overload scenario")
    try:
        for i in range(200):  # Try to overwhelm
            queue.enqueue(dummy_task, args=(i,), check_backpressure=True)
            if i % 20 == 0:
                print(f"📈 Enqueued {i + 1} jobs...")
    except BackpressureError as e:
        print(f"🛑 Backpressure fully blocked at {i + 1} jobs: {e}")

    print(f"\n📈 Final queue stats: {queue.stats()}")


# Main execution
if __name__ == "__main__":
    # Create queues
    adaptive_db = create_temp_path("adaptive_backpressure")
    priority_db = create_temp_path("priority_backpressure")

    adaptive_queue = AdaptiveBackpressureQueue(adaptive_db)
    priority_queue = PriorityBackpressureQueue(priority_db)

    # Start load simulation in background
    load_thread = threading.Thread(
        target=simulate_system_load, args=(adaptive_queue,), daemon=True
    )
    load_thread.start()

    print("🔄 Starting backpressure demonstration...")
    print("System load will vary automatically to simulate real-world conditions")

    # Run the backpressure tests
    batch_enqueue_with_backpressure(adaptive_queue, priority_queue)

    print("\n🎉 Backpressure demonstration complete!")
    print("💡 Key takeaways:")
    print("   • Adaptive thresholds adjust based on system load")
    print("   • Priority-based backpressure protects critical jobs")
    print("   • Load shedding prevents system overload")
    print("   • Different strategies for different workload patterns")
