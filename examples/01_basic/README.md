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

```python
from queuack import DuckQueue

queue = DuckQueue("jobs.db")
job_id = queue.enqueue(my_function, args=(42,))
```

**Difficulty:** Beginner
**Time:** 2 minutes

---

### 02_priority_jobs.py
**Priority-based job ordering**
- Set job priorities (0-100)
- Higher priority = processed first
- Use cases: urgent vs background tasks

```python
queue.enqueue(urgent_task, priority=90)
queue.enqueue(background_task, priority=10)
```

**Difficulty:** Beginner
**Time:** 2 minutes

---

### 03_delayed_jobs.py
**Schedule jobs for future execution**
- Delay job execution by seconds
- Use cases: retry delays, scheduled tasks, rate limiting

```python
# Run in 1 hour
queue.enqueue(send_reminder, delay_seconds=3600)
```

**Difficulty:** Beginner
**Time:** 2 minutes

---

### 04_batch_enqueue.py
**Efficiently enqueue multiple jobs**
- Batch operations for better performance
- Use cases: bulk processing, imports

```python
jobs = [(task1, (arg1,), {}), (task2, (arg2,), {})]
job_ids = queue.enqueue_batch(jobs)
```

**Difficulty:** Beginner
**Time:** 2 minutes

---

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
