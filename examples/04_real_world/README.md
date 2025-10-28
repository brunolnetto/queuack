# Real-World Examples

Production-ready patterns organized by domain. Each subdirectory contains examples for a specific use case category.

## Domains

### 📊 [01_etl/](01_etl/) - ETL & Data Pipelines
Process and transform data at scale.

**Examples:**
- Complete ETL with error handling
- Apache Spark integration
- Streaming ETL (1M+ records with ~50MB RAM)
- Multi-format exports (JSONL/CSV/Parquet/Pickle)

**Key features:** Memory-efficient streaming, Spark orchestration, multiple output formats

---

### 🌐 [02_web/](02_web/) - Web Scraping & APIs
HTTP requests, image processing, and API interactions.

**Examples:**
- Distributed web scraping with rate limiting
- Parallel image processing
- Report generation with parallel data fetching
- Async API fetching (50-100x speedup)

**Key features:** Async I/O, rate limiting, concurrent processing, error recovery

---

### 🤖 [03_ml/](03_ml/) - ML & MLOps
Replace Airflow, MLflow, and Kubeflow with Python + DuckDB.

**Examples:**
- Parallel hyperparameter tuning (no Ray needed)
- Complete ML pipeline orchestration (no Airflow/Kubeflow needed)
- ML training with model comparison

**Key features:**
- **Zero infrastructure** - 50MB RAM vs 4+ GB for traditional MLOps stack
- **Parallel training** - N workers for N-x speedup
- **SQLite tracking** - Query experiments with SQL
- **Local dev** - Same code on laptop and production

**Why Queuack for ML?**
```
Traditional: Airflow + MLflow + Kubeflow = 4+ GB RAM + K8s
Queuack:     Python + SQLite            = 50 MB RAM
```

---

## Quick Start by Domain

### ETL Pipeline
```python
from queuack import DuckQueue, generator_task

@generator_task(format="parquet")
def extract_data():
    for record in fetch_from_source():
        yield record

queue = DuckQueue("etl.db")
job_id = queue.enqueue(extract_data)
```

### Web Scraping
```python
from queuack import DuckQueue, async_task

@async_task
async def scrape_url(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()

queue = DuckQueue("scraper.db")
job_ids = [queue.enqueue(scrape_url, args=(url,)) for url in urls]
```

### ML Training
```python
from queuack import DuckQueue, Worker

def train_model(params):
    model = train(params)
    return {"accuracy": evaluate(model)}

queue = DuckQueue("ml.db")
param_grid = [{"lr": lr, "epochs": e} for lr in [0.001, 0.01, 0.1] for e in [10, 20]]
job_ids = [queue.enqueue(train_model, args=(p,)) for p in param_grid]

# Process in parallel
worker = Worker(queue, concurrency=4)
worker.process_pending()
```

---

## Performance Highlights

- **Streaming ETL**: Process 1M+ records with constant ~50MB memory
- **Async APIs**: 50-100x speedup for I/O-bound workloads
- **ML Training**: Same speed as Ray/Dask without infrastructure
- **Memory efficiency**: 10-100x less memory than in-memory approaches

See [main README](../../README.md) for more details.
