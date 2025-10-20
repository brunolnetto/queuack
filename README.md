# <img src="https://github.com/brunolnetto/queuack/raw/main/images/logo.png" width="32" alt="Queuack Logo"> Queuack - A lightweight job queue 

<img src="https://github.com/brunolnetto/queuack/raw/main/images/mascot.png" width="200" alt="Queuack Mascot">

Queuack (aka *DuckQueue*) is a pragmatic, single-node job queue that stores jobs in a DuckDB table.
It’s built for dev/test and small-to-medium production workloads where you want durability without the operational overhead of Redis/RabbitMQ/Celery.

This README is developer-focused: practical examples, caveats, and the exact behavior around backpressure and testing so you don't waste time chasing surprises.

---

## Highlights

* ✅ Persistent queue backed by **DuckDB** (file or `:memory:`)
* ✅ Claim / ack semantics with visibility timeout (stale-claim recovery)
* ✅ Priorities, delayed jobs, retries, dead-letter view
* ✅ Worker with optional thread-pool concurrency and backpressure control
* ⚠️ Job payloads are **pickled** callables & args (see security notes)
* Minimal runtime surface: `duckdb` + stdlib

---

## Requirements

* Python 3.11+ (tested on 3.12)
* `duckdb>=0.9.0`
* Optional: `pytest` / `pytest-cov` for tests

Install:

```bash
uv sync
```

---

## Quick usage

File: `example.py`

```python
import time
from queuack.core import DuckQueue, Worker, job

q = DuckQueue(":memory:")

def add(a, b):
    return a + b

# Enqueue directly
jid = q.enqueue(add, args=(2, 3))
print("job id:", jid)

# Decorator => add.delay()
@job(q, queue="default")
def greet(name):
    time.sleep(0.1)
    return f"hello {name}"

# Enqueue via decorator helper
greeting_job = greet.delay("Bruno")

# Claim + run manually (simple consumer)
job = q.claim()
if job:
    res = job.execute()
    q.ack(job.id, result=res)

# Or run a long-running worker (threaded)
w = Worker(q, queues=["default"], concurrency=2)
# w.run()  # blocks, use in a daemon/thread or run in your service
```

---

## Backpressure behavior — exact semantics you need to know

Queuack has two thresholds:

* **warning level** at **1000** pending jobs (configurable in code if you want)
* **hard limit** at **10000** pending jobs → raises `BackpressureError`

Important detail (this matters for tests):

* The code computes `pending = existing_pending + delayed` **before** inserting the job.
* The check uses `elif pending >= 1000:` to emit a `UserWarning` and log a warning.
  That means the **1001st** enqueue attempt (when `pending` is 1000 right before inserting) will trigger the `UserWarning`.

---

## API reference (core)

### `DuckQueue(db_path="duckqueue.db", default_queue="default")`

Create/open the DuckDB-backed queue.

* `db_path`: DuckDB file path or `":memory:"`
* `default_queue`: default name for enqueues/claims

### `enqueue(func, args=(), kwargs=None, queue=None, priority=50, delay_seconds=0, max_attempts=3, timeout_seconds=300, check_backpressure=True) -> str`

Serialize and insert a job. Returns job id (UUID).

* If `check_backpressure=True` will:

  * emit a `UserWarning` and log if pending >= 1000,
  * raise `BackpressureError` if pending > 10000.

### `enqueue_batch(jobs: List[(func, args, kwargs)], queue=None, priority=50, max_attempts=3) -> List[str]`

Insert many jobs in one transaction.

### `claim(queue=None, worker_id=None, claim_timeout=300) -> Optional[Job]`

Atomically claim the next eligible job and return a `Job` object. Implements stale-claim recovery if `claimed_at` older than `claim_timeout`.

### `ack(job_id, result=None, error=None)`

Acknowledge completion. If `error` provided and attempts < max_attempts, the job is requeued; otherwise moved to `failed`.

### `nack(job_id, requeue=True)`

Negative acknowledgement — default requeues.

### `stats(queue=None) -> dict`

Return counts by status (pending, claimed, done, failed, delayed).

### `get_job(job_id)`, `get_result(job_id)`, `list_dead_letters(limit=100)`, `purge(...)`

---

## Worker

`Worker(queue, queues=None, worker_id=None, concurrency=1, max_jobs_in_flight=None)`

* `queues` accepts `["default"]` or `[("emails", 100), ("reports", 50)]` to set claim order by priority.
* `concurrency` uses threads (ThreadPoolExecutor). CPU-bound jobs will be limited by the GIL — use processes externally if needed.
* `max_jobs_in_flight` defaults to `concurrency * 2` and is used for local backpressure (stop claiming when too many jobs in flight).

**Note:** `Worker.run()` registers signal handlers if run from the main thread (SIGINT / SIGTERM).

---

## Security & portability caveats

* Jobs serialize **callables** and args with `pickle`. This:

  * is **not safe** for untrusted input (pickle can execute arbitrary code on load),
  * makes job payloads **non-portable** across refactors (if function location or signature changes, old pickles may fail).
* If you need cross-language portability or safe deserialization, switch to JSON-serializable payloads or an external blob store + small metadata in DuckDB.

---

## Performance & scaling notes

* DuckDB works well for read-heavy analytical workloads — it handles our atomic updates fine for single-node or low-concurrency setups.
* Not intended for high-throughput broker-style workloads (millions of messages/s). For moderate use (thousands to tens of thousands of jobs), it’s fine.
* For heavy CPU jobs, run workers in processes (spawn separate Python processes each hosting a Worker instance) or offload to a process pool.

---

## Tests

Use `pytest`. Example:

```bash
pytest -q
```

---

## Roadmap / Ideas

* Optional JSON-serializable job payload mode
* Better instrumentation (prometheus metrics hooks)
* Process pool worker variant for CPU-bound workloads
* Web UI for inspections & replaying dead letters

---

## Contributing

Pull requests welcome. Keep changes small and include tests. If you change serialization behavior, add migration guidance.

Run test suite locally:

```bash
uv venv
source .venv/bin/activate
uv sync
pytest -q --cov=queuack
```

---

## License

MIT © 2025 Bruno Peixoto
