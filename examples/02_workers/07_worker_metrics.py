"""07_worker_metrics.py - Collect and report worker performance metrics

This example shows how to instrument workers for production monitoring:
- Track job processing times
- Count successes, failures, and retries
- Calculate throughput (jobs/second)
- Monitor worker efficiency
- Export metrics for dashboards

Key concepts:
- Metrics collection: Track performance data
- Performance monitoring: Identify bottlenecks
- Worker instrumentation: Add observability
- Production readiness: Essential for deployed systems

# Difficulty: intermediate
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

@dataclass
class WorkerMetrics:
    """Track worker performance metrics."""
    jobs_processed: int = 0
    jobs_failed: int = 0
    jobs_retried: int = 0
    total_processing_time: float = 0.0
    start_time: datetime = field(default_factory=datetime.now)
    processing_times: list = field(default_factory=list)
    
    def record_success(self, duration: float):
        """Record a successful job completion."""
        self.jobs_processed += 1
        self.total_processing_time += duration
        self.processing_times.append(duration)
    
    def record_failure(self):
        """Record a job failure."""
        self.jobs_failed += 1
    
    def record_retry(self):
        """Record a job retry."""
        self.jobs_retried += 1
    
    def get_stats(self) -> Dict:
        """Calculate and return current statistics."""
        runtime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            'jobs_processed': self.jobs_processed,
            'jobs_failed': self.jobs_failed,
            'jobs_retried': self.jobs_retried,
            'runtime_seconds': runtime,
            'throughput_per_sec': self.jobs_processed / runtime if runtime > 0 else 0,
            'avg_job_time': (
                self.total_processing_time / self.jobs_processed 
                if self.jobs_processed > 0 else 0
            ),
            'min_job_time': min(self.processing_times) if self.processing_times else 0,
            'max_job_time': max(self.processing_times) if self.processing_times else 0,
        }
    
    def print_report(self):
        """Print a formatted metrics report."""
        stats = self.get_stats()
        print("\n📊 Worker Metrics Report")
        print("========================")
        print(f"Runtime:        {stats['runtime_seconds']:.2f}s")
        print(f"Jobs Processed: {stats['jobs_processed']}")
        print(f"Jobs Failed:    {stats['jobs_failed']}")
        print(f"Jobs Retried:   {stats['jobs_retried']}")
        print(f"Throughput:     {stats['throughput_per_sec']:.2f} jobs/sec")
        print(f"Avg Job Time:   {stats['avg_job_time']:.3f}s")
        print(f"Min Job Time:   {stats['min_job_time']:.3f}s")
        print(f"Max Job Time:   {stats['max_job_time']:.3f}s")

def variable_duration_task(duration: float):
    """Task with variable duration for metrics testing."""
    time.sleep(duration)
    return f"Completed in {duration}s"

def sometimes_fails(fail_chance: float):
    """Task that sometimes fails for metrics testing."""
    import random
    if random.random() < fail_chance:
        raise ValueError("Task failed randomly")
    return "Success"

db_path = create_temp_path("metrics")
queue = DuckQueue(db_path)

print("🦆 Worker Metrics Example")
print("==========================")
print("This example shows how to collect and report worker metrics.")
print()

# Enqueue mix of tasks
print("📝 Enqueuing 20 test jobs (mix of fast and slow)...")
for i in range(20):
    # Mix of fast (0.1s) and slow (0.5s) tasks
    duration = 0.1 if i % 2 == 0 else 0.5
    queue.enqueue(variable_duration_task, args=(duration,))

# Add some jobs that might fail
for i in range(5):
    queue.enqueue(sometimes_fails, args=(0.3,), max_attempts=2)

print(f"Total jobs enqueued: 25")
print()

# Worker with metrics
metrics = WorkerMetrics()
print("🚀 Starting instrumented worker...")

empty_polls = 0
while empty_polls < 3:
    job = queue.claim()
    
    if job:
        empty_polls = 0
        job_start = time.perf_counter()
        
        try:
            result = job.execute()
            duration = time.perf_counter() - job_start
            queue.ack(job.id, result=result)
            metrics.record_success(duration)
            
            # Print periodic updates
            if metrics.jobs_processed % 5 == 0:
                print(f"⏱️  Processed {metrics.jobs_processed} jobs "
                      f"({metrics.get_stats()['throughput_per_sec']:.1f} jobs/sec)")
        
        except Exception as e:
            queue.ack(job.id, error=str(e))
            metrics.record_failure()
            
            # Check if this was a retry
            if job.attempts > 1:
                metrics.record_retry()
                print(f"🔄 Job retry detected (attempt {job.attempts})")
    else:
        empty_polls += 1
        time.sleep(1.0)

# Print final report
metrics.print_report()