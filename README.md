# <img src="https://github.com/brunolnetto/queuack/raw/main/images/logo.png" width="32" alt="Queuack Logo"> Queuack - DuckDB-Powered Job Queue & DAG Engine
[![Version](https://img.shields.io/pypi/v/queuack.svg)](https://pypi.python.org/pypi/queuack)
[![codecov](https://codecov.io/github/brunolnetto/queuack/graph/badge.svg?token=N7JC4BP26Q)](https://codecov.io/github/brunolnetto/queuack)
[![downloads](https://img.shields.io/pypi/dm/queuack)](https://pypi.org/project/queuack/)


<img src="https://github.com/brunolnetto/queuack/raw/main/images/mascot.png" width="200" alt="Queuack Mascot">

Queuack is a pragmatic, single-node job queue that stores jobs in a DuckDB table. It’s built for dev/test and small-to-medium production workloads where you want durability without the operational overhead of Redis/RabbitMQ/Celery.

Perfect for dev/test environments and small-to-medium production workloads where you want:
- ✅ **Persistent queues** without Redis/RabbitMQ complexity
- ✅ **DAG workflows** without Airflow's operational overhead
- ✅ **Memory-efficient streaming** for processing massive datasets
- ✅ **Beautiful visualizations** with customizable Mermaid diagrams
- ✅ **Zero external dependencies** (just DuckDB + stdlib)

---

## Table of Contents

- [Why Queuack?](#why-queuack)
- [Quick Start](#quick-start)
  - [Installation](#installation)
  - [Basic Queue (30 seconds)](#basic-queue-30-seconds)
  - [DAG Workflow (1 minute)](#dag-workflow-1-minute)
  - [Streaming ETL (2 minutes)](#streaming-etl-2-minutes)
  - [Async I/O (1 minute)](#async-io-1-minute)
  - [ML Pipeline (3 minutes)](#ml-pipeline-3-minutes)
  - [Key Features](#key-features)
  - [Job Queue](#1-job-queue---redis-free-persistence)
  - [DAG Workflows](#2-dag-workflows---complex-pipelines-made-simple)
  - [Memory-Efficient Streaming](#3-memory-efficient-streaming---process-billions-of-rows)
  - [Beautiful Visualizations](#4-beautiful-visualizations---6-customizable-themes)
  - [Production-Ready Features](#5-production-ready-features)
- [Documentation & Examples](#documentation--examples)
- [Architecture](#architecture)
- [Configuration & Tuning](#configuration--tuning)
- [Security Considerations](#security-considerations)
- [Performance & Scaling](#performance--scaling)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)
- [Support](#support)

---

## 🎯 Why Queuack?

| Feature | Queuack | Celery + Redis | Airflow | MLflow + Kubeflow |
|---------|---------|----------------|---------|-------------------|
| **Setup** | `pip install queuack` | Install Redis, configure Celery | Docker compose, PostgreSQL, webserver | K8s cluster, multiple servers |
| **DAG Workflows** | ✅ Built-in | ❌ Separate tools | ✅ Core feature | ✅ Complex setup |
| **Streaming ETL** | ✅ O(1) memory | ❌ Load all data | ⚠️ Manual batching | ⚠️ Manual setup |
| **ML Pipelines** | ✅ Native support | ⚠️ Manual | ⚠️ Complex | ✅ Core feature |
| **Visualization** | ✅ Mermaid (6 themes) | ❌ None | ✅ Web UI (complex) | ✅ Web UI (complex) |
| **Local Development** | ✅ Single file | ⚠️ Need Redis | ⚠️ Need full stack | ❌ Need K8s |
| **Memory Footprint** | ~50 MB | ~200 MB | ~2 GB | ~4 GB |

**Perfect for:**
- 🔬 **ML Engineers** - Train models without Kubernetes
- 📊 **Data Engineers** - Build ETL pipelines without Airflow overhead
- 🚀 **Startups** - Ship fast without infrastructure complexity
- 💻 **Solo Developers** - Full workflow engine on your laptop

---

## 🚀 Quick Start

### Installation

```bash
pip install queuack

# Optional: For Parquet support
pip install queuack[parquet]
```

### Basic Queue (30 seconds)

```python
from queuack import DuckQueue, Worker

# Create queue
queue = DuckQueue("jobs.db")  # or ":memory:" for testing

# Enqueue a job
def process_data(x):
    return x * 2

job_id = queue.enqueue(process_data, args=(42,))

# Process jobs
worker = Worker(queue, concurrency=4)
worker.run()  # Blocks and processes jobs
```

### DAG Workflow (1 minute)

```python
from queuack import DAG, DuckQueue

queue = DuckQueue(":memory:")
dag = DAG("etl_pipeline", queue=queue)

# Define tasks
def extract():
    return {"records": 1000}

def transform(context):
    data = context.upstream("extract")
    return {"processed": data["records"] * 2}

def load(context):
    result = context.upstream("transform")
    print(f"Loaded {result['processed']} records")
    return {"status": "success"}

# Build pipeline
dag.add_node(extract, name="extract")
dag.add_node(transform, name="transform", depends_on=["extract"])
dag.add_node(load, name="load", depends_on=["transform"])

# Execute
dag.execute()
```

### Streaming ETL (2 minutes)

```python
from queuack import generator_task, StreamReader

# Process 1 million records with ~50MB memory
@generator_task(format="parquet")  # or csv, jsonl, pickle
def extract_data():
    for i in range(1_000_000):
        yield {"id": i, "value": i * 2}

# Returns path to Parquet file
output_path = extract_data()

# Read lazily - one row at a time!
reader = StreamReader(output_path)
for row in reader:
    process(row)  # Memory stays constant
```

### Async I/O (1 minute)

```python
from queuack import async_task
import asyncio

# 10-100x speedup for I/O-bound tasks
@async_task
async def fetch_data(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return [await r.json() for r in responses]

# Call synchronously - decorator handles event loop
results = fetch_data(["url1", "url2", ..., "url50"])
# Completes in ~0.1s instead of ~5s (50x faster!)
```

### ML Pipeline (3 minutes)

```python
from queuack import DAG, DuckQueue

# Replace Airflow + MLflow + Kubeflow with 50 MB
queue = DuckQueue("ml_pipeline.db")
dag = DAG("model_training", queue=queue)

# Build ML pipeline
dag.add_node(ingest_data, name="ingest")
dag.add_node(validate_data, name="validate", depends_on=["ingest"])
dag.add_node(engineer_features, name="features", depends_on=["validate"])
dag.add_node(train_model, name="train", depends_on=["features"])
dag.add_node(evaluate_model, name="evaluate", depends_on=["train"])
dag.add_node(deploy_model, name="deploy", depends_on=["evaluate"])

# Execute pipeline - all state tracked in SQLite
dag.execute()

# Parallel hyperparameter search
for params in param_grid:  # 54 combinations
    queue.enqueue(train_model, args=(params,))
# Trains 4x faster with 4 workers, no Ray/Dask needed
```

---

## ✨ Key Features

### 1. **Job Queue** - Redis-free persistence

```python
# Priorities, delays, retries, timeouts
queue.enqueue(
    send_email,
    args=("user@example.com",),
    priority=90,           # 0-100 (higher = sooner)
    delay_seconds=3600,    # Schedule for later
    max_attempts=5,        # Retry failed jobs
    timeout_seconds=300    # Job timeout
)

# Batch operations
job_ids = queue.enqueue_batch([
    (task1, (arg1,), {}),
    (task2, (arg2,), {}),
])

# Monitor
stats = queue.stats()
# {'pending': 42, 'claimed': 3, 'done': 1250, 'failed': 5}
```

### 2. **DAG Workflows** - Complex pipelines made simple

```python
# Fan-out/fan-in pattern
dag.add_node(extract, name="extract")
dag.add_node(transform_a, name="transform_a", depends_on=["extract"])
dag.add_node(transform_b, name="transform_b", depends_on=["extract"])
dag.add_node(load, name="load", depends_on=["transform_a", "transform_b"])

# Conditional execution (ANY mode)
dag.add_node(
    validate,
    name="validate",
    depends_on=["source_a", "source_b"],
    dependency_mode="any"  # Run when ANY parent completes
)

# Sub-DAGs for reusability
preprocessing_dag = create_preprocessing_dag()
dag.add_subdag(preprocessing_dag, name="preprocess")
```

### 3. **Memory-Efficient Streaming** - Process billions of rows

```python
from queuack import generator_task, StreamReader, StreamWriter

# Write generator → file (O(1) memory)
@generator_task(format="parquet")
def extract():
    for i in range(100_000_000):  # 100M rows!
        yield {"id": i, "data": process(i)}

# Supports 4 formats:
# - JSONL: Human-readable, universal
# - CSV: Excel-compatible
# - Parquet: Analytics, Spark/Pandas
# - Pickle: Complex Python objects
```

**Memory comparison:**
- Traditional: Load all → 14 GB RAM ❌
- Streaming: ~50 MB RAM ✅

### 4. **Beautiful Visualizations** - 6 customizable themes

```python
from queuack import MermaidColorScheme

# Pre-built themes
dark = MermaidColorScheme.dark_mode()
professional = MermaidColorScheme.blue_professional()
accessible = MermaidColorScheme.high_contrast()

# Generate diagram
mermaid = dag.export_mermaid(color_scheme=dark)

# Paste into GitHub/GitLab Markdown:
# ```mermaid
# [paste here]
# ```
```

**Available themes:** default, blue_professional, dark_mode, pastel, high_contrast, grayscale

### 5. **Production-Ready Features**

- ✅ **Backpressure control** - Automatic throttling at 10k pending jobs
- ✅ **Graceful shutdown** - SIGTERM/SIGINT handling
- ✅ **Dead letter queue** - Failed job inspection
- ✅ **Claim recovery** - Auto-recover stuck jobs
- ✅ **Multi-queue workers** - Priority-based claiming
- ✅ **Concurrent execution** - Thread pool workers
- ✅ **Transaction safety** - ACID guarantees via DuckDB

---

## 📚 Documentation & Examples

### Examples Structure

Our examples follow a **progressive learning path**:

#### [01_basic/](examples/01_basic) - Core Concepts
- Simple queue operations
- Priority and delayed jobs
- Batch operations

#### [02_workers/](examples/02_workers) - Worker Patterns
- Single and concurrent workers
- Multi-queue processing
- Graceful shutdown

#### [03_dag_workflows/](examples/03_dag_workflows) - DAG Patterns
- Linear pipelines
- Fan-out/fan-in
- Conditional execution
- Diamond dependencies
- Sub-DAGs

#### [04_real_world/](examples/04_real_world) - Production Use Cases
- ETL pipelines
- Web scraping
- Image processing
- ML training pipelines
- **NEW!** Streaming ETL (1M+ records)
- **NEW!** Multi-format exports (JSONL/CSV/Parquet)
- **NEW!** Async API fetching (50x faster)

#### [05_advanced/](examples/05_advanced) - Advanced Techniques
- Custom backpressure
- Monitoring dashboards
- Distributed workers
- **NEW!** Custom Mermaid color schemes

#### [06_integration/](examples/06_integration) - Framework Integration
- Flask, FastAPI, Django
- CLI tools

#### [07_mlops/](examples/07_mlops) - ML Engineering **NEW!**
- **Parallel hyperparameter tuning** - Replace Ray/MLflow
- **Complete ML pipelines** - Replace Airflow/Kubeflow
- Experiment tracking in SQLite
- Model training and deployment
- No Kubernetes required!

**Run any example:**
```bash
cd examples/04_real_world
python 07_streaming_etl.py
```

---

## 🏗️ Architecture

### Queue Storage
- **Engine:** DuckDB (embedded OLAP database)
- **Schema:** Single `jobs` table with indexes
- **Locking:** File-based for multi-process safety
- **Transactions:** ACID compliance for atomic operations

### Job Execution
- **Serialization:** Pickle (functions + arguments)
- **Concurrency:** ThreadPoolExecutor per worker
- **Claim Semantics:** Visibility timeout with stale recovery
- **Retry Logic:** Exponential backoff (configurable)

### DAG Execution
- **Graph Engine:** NetworkX for topological sorting
- **Scheduling:** Level-based parallel execution
- **Dependencies:** ALL (default) or ANY mode
- **Status Tracking:** Real-time job status monitoring

### Streaming Engine
- **Memory Model:** O(1) constant memory usage
- **Batch Processing:** 10k row batches for Parquet
- **Format Support:** JSONL, CSV, Parquet, Pickle
- **Lazy Reading:** Generator-based iteration

---

## ⚙️ Configuration & Tuning

### Queue Configuration

```python
queue = DuckQueue(
    db_path="jobs.db",          # or ":memory:"
    default_queue="default",
    workers_num=4,               # Auto-start workers
    worker_concurrency=2,        # Threads per worker
    poll_timeout=1.0,            # Claim polling interval
    serialization="pickle"       # or "json_ref"
)
```

### Worker Configuration

```python
worker = Worker(
    queue,
    queues=[
        ("high_priority", 100),
        ("normal", 50),
        ("low", 10)
    ],
    concurrency=8,               # Thread pool size
    worker_id="worker-01"        # For distributed setups
)
```

### DAG Configuration

```python
dag = DAG(
    name="pipeline",
    queue=queue,
    max_retries=3,
    retry_delay=60,
    timeout_per_task=600,
    show_progress=True           # Progress bar
)
```

### Backpressure Thresholds

```python
# Customize in subclass
class MyQueue(DuckQueue):
    @classmethod
    def backpressure_warning_threshold(cls):
        return 5000  # Warn at 5k pending

    @classmethod
    def backpressure_block_threshold(cls):
        return 50000  # Block at 50k pending
```

---

## 🔒 Security Considerations

### Pickle Serialization
- ⚠️ **Not safe for untrusted input** - Pickle can execute arbitrary code
- ⚠️ **Not portable across refactors** - Function signature changes break old pickles
- ✅ **Fast and convenient** - Works with any Python object

**Mitigations:**
1. Use `serialization="json_ref"` mode (functions by reference only)
2. Validate all job inputs before enqueueing
3. Run workers in sandboxed environments
4. Keep function signatures stable

### Multi-Process Safety
- ✅ File-based locking for concurrent workers
- ✅ Automatic stale claim recovery
- ⚠️ Avoid `:memory:` with multiple workers (use temp file instead)

---

## 📊 Performance & Scaling

### Throughput Benchmarks
- **Enqueue:** ~5,000 jobs/second (batch mode)
- **Claim:** ~1,000 claims/second (single worker)
- **Execute:** Limited by job duration + thread pool

### Scaling Guidelines

| Jobs/Day | Workers | Concurrency | DB Size |
|----------|---------|-------------|---------|
| < 10k | 1 | 2-4 | < 100 MB |
| 10k - 100k | 2-4 | 4-8 | 100 MB - 1 GB |
| 100k - 1M | 4-8 | 8-16 | 1-10 GB |
| > 1M | 8+ | 16+ | 10+ GB |

**Tips:**
- Purge completed jobs regularly (`queue.purge()`)
- Use multiple queues for different priorities
- Run workers on same host as DB file (avoid network file systems)
- For CPU-bound jobs, use process-based workers
- Monitor with `queue.stats()` and `dag.get_progress()`

---

## 🧪 Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=queuack --cov-report=html

# Specific test suite
pytest tests/test_dag.py -v

# Fast tests only (skip slow integration tests)
pytest -k "not test_large"
```

---

## 🗺️ Roadmap

### Completed ✅
- [x] Basic queue with priorities and delays
- [x] DAG workflow engine
- [x] Generator streaming (O(1) memory)
- [x] Multi-format support (CSV, Parquet, JSONL, Pickle)
- [x] Mermaid visualization with themes
- [x] Sub-DAG support
- [x] Async/await support for I/O-heavy tasks

### In Progress 🚧
- [ ] Storage backend abstraction (SQLite, PostgreSQL)
- [ ] Web UI for monitoring
- [ ] Prometheus metrics

### Planned 📋
- [ ] Scheduled/cron jobs
- [ ] Job priorities within DAGs
- [ ] Dynamic DAG generation
- [ ] Result caching
- [ ] Job pause/resume

---

## 🤝 Contributing

We welcome contributions! Please:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feat/amazing-feature`)
3. **Write** tests for your changes
4. **Ensure** tests pass (`pytest`)
5. **Commit** your changes (`git commit -m 'feat: Add amazing feature'`)
6. **Push** to the branch (`git push origin feat/amazing-feature`)
7. **Open** a Pull Request

**Development setup:**
```bash
# Clone repo
git clone https://github.com/brunolnetto/queuack.git
cd queuack

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest -v
```

---

## 📄 License

MIT © 2025 Bruno Peixoto

---

## 🙏 Acknowledgments

- Built with [DuckDB](https://duckdb.org/) - Fast in-process analytical database
- DAG engine inspired by [Airflow](https://airflow.apache.org/), simplified for single-node use
- Visualization powered by [Mermaid](https://mermaid.js.org/)

---

## 📞 Support

- **Documentation:** [examples/](examples/)
- **Issues:** [GitHub Issues](https://github.com/brunolnetto/queuack/issues)
- **Discussions:** [GitHub Discussions](https://github.com/brunolnetto/queuack/discussions)

---

**Made with 🦆 and ❤️ by the Queuack team**
