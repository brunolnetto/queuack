# Real-World Examples

Production-ready patterns organized by domain. Each subdirectory contains examples for a specific use case category.

## Domains

### 🌐 [01_web/](01_web/) - Web & API
Web scraping, image processing, async APIs, batch email, and webhook processing.

**Examples:**
- Distributed web scraping with rate limiting
- Parallel image processing
- Report generation with parallel data fetching
- Async API fetching (50x speedup)
- Batch email sending with async and DAG parallelization
- Webhook processing with async, retries, and error handling

---

### 📊 [02_etl/](02_etl/) - ETL & Data Pipelines
Production-ready ETL patterns for data engineering workflows.

**Examples:**
- Complete ETL with error handling
- Apache Spark integration
- Streaming ETL (1M+ records, ~50MB RAM)
- Multi-format exports (JSONL/CSV/Parquet/Pickle)

---

### 🤖 [03_ml/](03_ml/) - ML & MLOps
ML pipelines, hyperparameter search, scikit-learn, MLflow, DVC, and PyTorch integration.

**Examples:**
- Parallel hyperparameter tuning (no Ray needed)
- Complete ML pipeline orchestration (no Airflow/Kubeflow needed)
- Scikit-learn classification and ensemble pipelines
- MLflow experiment tracking and model registry
- DVC data versioning
- PyTorch + MLflow + DVC full-stack MLOps

---

### 🔗 [04_integration/](04_integration/) - Framework Integration
Integrate Queuack with Flask, FastAPI, Django, and CLI tools.

**Examples:**
- Flask API with background job processing
- FastAPI async integration
- Django background tasks
- Command-line management tool

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
