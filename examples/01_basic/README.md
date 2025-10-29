# Basic Examples

**Learn Queuack fundamentals in 5 minutes**

Start here if you're new to Queuack. These examples cover core queue operations, job management, and basic patterns.

## Examples


### 01_simple_queue.py
**Basic producer/consumer pattern**
- Create a queue
- Enqueue jobs
- Claim and process jobs
- Basic error handling

### 02_priority_jobs.py
**Priority-based job ordering**
- Set job priorities (0-100)
- Higher priority = processed first
- Use cases: urgent vs background tasks

### 03_delayed_jobs.py
**Schedule jobs for future execution**
- Delay job execution by seconds
- Use cases: retry delays, scheduled tasks, rate limiting

### 04_batch_enqueue.py
**Efficiently enqueue multiple jobs**
- Batch operations for better performance
- Use cases: bulk processing, imports

### 05_error_handling.py
**Error handling and retries**
- Demonstrates automatic retries for flaky jobs
- Shows how to handle and log errors

### 06_results_and_dlq.py
**Results and Dead Letter Queue (DLQ)**
- Retrieve job results after completion
- Handle jobs that fail permanently (DLQ)

### 07_queue_stats.py
**Queue stats and monitoring**
- Monitor queue health and job status counts
- Print stats before and after processing

### 08_context_manager.py
**Using DuckQueue as a context manager**
- Auto-start/stop workers with `with` block
- Demonstrates background processing

### 09_backpressure.py
**Backpressure and throttling**
- Demonstrates `BackpressureError` and producer throttling
- Shows how to relieve pressure by processing jobs

### 10_purging.py
**Purging completed jobs**
- Demonstrates `queue.purge()` to clean up old jobs
- Shows stats before and after purging

## Running Examples

```bash
# Interactive mode
python scripts/run_examples.py

# Run specific example
python scripts/run_examples.py run 1.1

# Run all basic examples
python scripts/run_examples.py run-category basic
```

---

## Next Steps

After mastering these basics, continue to:
- **[02_workers/](../02_workers/)** - Learn about worker processes
- **[03_dag_workflows/](../03_dag_workflows/)** - Build complex workflows
- **[04_real_world/](../04_real_world/)** - See production patterns

---

## Key Concepts

### Queue
Persistent job storage backed by DuckDB (SQLite-compatible)

### Job
Unit of work containing:
- Function to execute
- Arguments
- Metadata (priority, status, retries)

### Enqueue
Add job to queue for processing

### Claim
Worker grabs next available job (by priority)

### Ack
Mark job as completed successfully

---

**Questions?** Check the [main README](../../README.md) or [examples overview](../README.md)
