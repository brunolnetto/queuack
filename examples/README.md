# Queuack Examples

This directory contains practical examples demonstrating Queuack's features from basic to advanced use cases.

## Quick Start

```bash
# Install Queuack
pip install queuack

# Run a basic example
python 01_basic/simple_queue.py

# Start a worker
python 02_workers/single_worker.py
```

## Directory Structure

### 01_basic/ - Getting Started
Learn the fundamentals: enqueue, claim, ack, priorities, delays, and batch operations.

**Start here if you're new to Queuack.**

- `simple_queue.py` - Basic producer/consumer pattern
- `priority_jobs.py` - Priority-based job ordering
- `delayed_jobs.py` - Schedule jobs for future execution
- `batch_enqueue.py` - Efficiently enqueue multiple jobs

### 02_workers/ - Worker Patterns
Understand how to build robust worker processes with concurrency, multi-queue support, and graceful shutdown.

- `single_worker.py` - Basic long-running worker
- `concurrent_workers.py` - Multi-threaded parallel execution
- `multi_queue_worker.py` - Process multiple queues with priorities
- `graceful_shutdown.py` - Handle signals properly

### 03_dag_workflows/ - DAG Patterns
Master complex workflows with dependencies, parallel execution, and conditional logic.

- `linear_pipeline.py` - Simple A → B → C pipeline
- `fan_out_fan_in.py` - Parallel processing with synchronization
- `conditional_execution.py` - OR-based dependencies (ANY mode)
- `diamond_dependency.py` - Diamond pattern synchronization
- `external_dependencies.py` - Reference external jobs

### 04_real_world/ - Production Use Cases
Real-world examples you can adapt for your projects.

- `etl_pipeline.py` - Complete ETL with error handling
- `web_scraper.py` - Distributed web scraping with rate limiting
- `image_processing.py` - Parallel image processing
- `report_generator.py` - Report generation with parallel data fetching
- `ml_training_pipeline.py` - ML training with model comparison
- `07_streaming_etl.py` - **NEW!** Memory-efficient streaming ETL (1M+ records)
- `08_streaming_formats.py` - **NEW!** Multi-format exports (JSONL/CSV/Parquet/Pickle)
- `09_async_api_fetching.py` - **NEW!** Async I/O for 10-100x speedup (API requests)

### 05_advanced/ - Advanced Patterns
Advanced techniques for production deployments.

- `custom_backpressure.py` - Custom backpressure thresholds
- `monitoring_dashboard.py` - Real-time queue monitoring
- `distributed_workers.py` - Multi-machine worker deployment
- `retry_strategies.py` - Advanced retry patterns
- `dag_visualization.py` - Generate DAG diagrams
- `06_custom_colors.py` - **NEW!** Custom Mermaid color schemes (6 themes)

### 06_integrations/ - Framework Integration
Integrate Queuack with popular web frameworks.

- `flask_api.py` - Flask API with background jobs
- `fastapi_background.py` - FastAPI async integration
- `django_tasks.py` - Django background tasks
- `cli_tool.py` - Command-line management tool

## Running Examples

### Basic Queue Example

```bash
cd 01_basic
python simple_queue.py
```

### Worker Example

```bash
# Terminal 1: Enqueue jobs
python -c "
from queuack import DuckQueue
queue = DuckQueue('test.db')
for i in range(10):
    queue.enqueue(lambda x: print(x), args=(i,))
"

# Terminal 2: Run worker
cd 02_workers
python single_worker.py
```

### DAG Example

```bash
cd 03_dag_workflows
python linear_pipeline.py

# Then start worker to process the DAG
python ../02_workers/single_worker.py
```

### Real-world ETL Pipeline

```bash
cd 04_real_world
python etl_pipeline.py

# Monitor progress
python ../05_advanced/monitoring_dashboard.py
```

## Best Practices

### 1. Function Picklability
Functions must be module-level (not lambdas or nested):

```python
# ✓ Good
def process_data(x):
    return x * 2

queue.enqueue(process_data, args=(5,))

# ✗ Bad
queue.enqueue(lambda x: x * 2, args=(5,))  # Won't pickle!
```

### 2. Error Handling
Always set appropriate `max_attempts` and `timeout_seconds`:

```python
queue.enqueue(
    flaky_api_call,
    max_attempts=5,        # Retry up to 5 times
    timeout_seconds=300    # 5 minute timeout
)
```

### 3. Backpressure
Use `check_backpressure=True` for producer throttling:

```python
try:
    queue.enqueue(task, check_backpressure=True)
except BackpressureError:
    # Queue is full, slow down!
    time.sleep(10)
```

### 4. DAG Dependencies
Use named nodes for readability:

```python
with queue.dag("pipeline") as dag:
    extract = dag.enqueue(extract_func, name="extract")
    transform = dag.enqueue(
        transform_func,
        name="transform",
        depends_on="extract"  # Use name, not job ID
    )
```

### 5. Worker Concurrency
Match concurrency to workload:

```python
# CPU-bound tasks: concurrency = CPU cores
Worker(queue, concurrency=4)

# I/O-bound tasks: concurrency = 10-50
Worker(queue, concurrency=20)
```

## Production Deployment

### Multi-worker Setup

```bash
# Machine 1: Run worker
python -m queuack.worker --db=/shared/queue.db --concurrency=8

# Machine 2: Run worker
python -m queuack.worker --db=/shared/queue.db --concurrency=8

# Machine 3: Enqueue jobs
python producer.py
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run worker
CMD ["python", "-m", "queuack.worker", "--db=/data/queue.db"]
```

### Monitoring

```bash
# Use CLI tool
pip install queuack[cli]

# Check stats
queuack --db queue.db stats

# Monitor DAG
queuack --db queue.db dag-status 

# Start worker
queuack --db queue.db worker --concurrency=4
```

## Testing Examples

All examples include inline tests. Run with pytest:

```bash
pytest 01_basic/
pytest 03_dag_workflows/
pytest --verbose  # Detailed output
```

## Performance Tips

1. **Batch Operations**: Use `enqueue_batch()` for bulk inserts
2. **Connection Pooling**: One DB file per queue for hot paths
3. **Purge Old Jobs**: Run `queue.purge()` regularly
4. **Index Optimization**: Default indexes are sufficient for most cases
5. **Worker Placement**: Colocate workers with data sources

## Troubleshooting

### Jobs stuck in "claimed" status
- Worker crashed without releasing claim
- Wait for claim timeout (default: 300s) or restart worker

### High memory usage
- Purge completed jobs regularly
- Reduce worker concurrency
- Process large data in chunks

### Slow job claiming
- Check database file location (SSD vs HDD)
- Reduce job count via purging
- Split into multiple queues

## Contributing

Have a useful example? Submit a PR:

1. Add to appropriate directory
2. Include docstring and inline comments
3. Add entry to this README
4. Ensure code is self-contained and runnable

## Support

- Documentation: https://queuack.readthedocs.io
- Issues: https://github.com/queuack/queuack/issues
- Discussions: https://github.com/queuack/queuack/discussions

## License

All examples are MIT licensed - use them freely in your projects.