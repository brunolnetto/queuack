# Framework Integration Examples

Integrate Queuack with popular web frameworks and tools.

## Examples

### 01_flask_api.py
**Flask API with background job processing**
- Enqueue and track jobs from HTTP endpoints.

### 02_fastapi_background.py
**FastAPI async integration**
- Background workers and async endpoints.

### 03_django_tasks.py
**Django background tasks**
- Enqueue jobs from views, run workers as management commands.

### 04_cli_tool.py
**Command-line management tool**
- Inspect, manage, and operate the queue from the CLI.

## Quick Start

```python
# Flask
from flask import Flask
from queuack import DuckQueue

app = Flask(__name__)
queue = DuckQueue("jobs.db")

@app.route("/process")
def process():
    job_id = queue.enqueue(heavy_task, args=(data,))
    return {"job_id": job_id}
```

See [main README](../../README.md) for more details.
