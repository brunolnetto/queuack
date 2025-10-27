# Worker Examples

Learn how to build robust worker processes with concurrency, multi-queue support, and graceful shutdown.

## Examples

- `01_single_worker.py` - Basic long-running worker
- `02_concurrent_workers.py` - Multi-threaded parallel execution
- `03_multi_queue_worker.py` - Process multiple queues with priorities
- `04_graceful_shutdown.py` - Handle SIGTERM/SIGINT properly

## Quick Start

```python
from queuack import DuckQueue, Worker

queue = DuckQueue("jobs.db")
worker = Worker(queue, concurrency=4)
worker.run()  # Blocks and processes jobs
```

See [main README](../../README.md) for more details.
