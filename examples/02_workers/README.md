# Worker Examples

Learn how to build robust worker processes with concurrency, multi-queue support, and graceful shutdown.

## Examples


### 01_single_worker.py
**Basic long-running worker**
- Sequentially processes jobs until the queue is empty.

### 02_concurrent_workers.py
**Multi-threaded worker**
- Processes jobs in parallel using multiple threads.

### 03_multi_queue_worker.py
**Multi-queue worker**
- Listens to multiple named queues with priorities.

### 04_graceful_shutdown.py
**Graceful shutdown**
- Handles SIGTERM/SIGINT, finishes active jobs before exit.

### 05_health_checks.py
**Health checks**
- Monitors worker liveness and queue progress.

### 06_backpressure_worker.py
**Backpressure handling**
- Adapts to queue load, slows down when full.

### 07_worker_metrics.py
**Worker metrics**
- Collects and reports job processing performance.

### 08_worker_metrics.py
**DLQ worker**
- Processes failed jobs with retry and error classification.

### 09_dynamics_scaling.py
**Dynamic scaling**
- Auto-scales worker pool size based on queue depth.

## Quick Start

```python
from queuack import DuckQueue, Worker

queue = DuckQueue("jobs.db")
worker = Worker(queue, concurrency=4)
worker.run()  # Blocks and processes jobs
```

See [main README](../../README.md) for more details.
