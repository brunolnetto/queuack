# Advanced Queuack Examples

This directory contains advanced examples demonstrating sophisticated queue management patterns, monitoring, and integration techniques.

## Examples Overview

### 01_custom_backpressure.py
**Custom Backpressure Policies**

Demonstrates adaptive backpressure thresholds and load shedding strategies:
- Adaptive thresholds based on system load and job priority
- Priority-based backpressure (high, normal, low priority jobs)
- Load shedding for low-priority jobs during high load
- Simulated system load variations (business hours vs off-hours)

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/01_custom_backpressure.py
```

**Key Concepts:**
- Backpressure warning vs blocking thresholds
- Priority-based queue management
- Adaptive policies based on system metrics
- Graceful degradation under load

### 02_monitoring_dashboard.py
**Real-time Web Monitoring Dashboard**

Built-in HTTP server with WebSocket updates for live queue monitoring:
- Real-time metrics collection and visualization
- Chart.js-powered performance charts
- Alert system for queue health issues
- Historical trend analysis
- Multi-queue monitoring support

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/02_monitoring_dashboard.py
```

Then open http://localhost:8080 in your browser.

**Key Concepts:**
- Real-time monitoring with WebSocket updates
- REST API endpoints for metrics
- Interactive charts and alerts
- Historical data analysis
- Built-in web server

### 03_flask_monitoring_dashboard.py
**Flask-based Monitoring Dashboard PoC**

Persistent web application using Flask and Flask-SocketIO:
- Flask web framework integration
- WebSocket real-time updates
- RESTful API design
- Production-ready web application structure
- Chart.js visualization with live updates

**Dependencies:**
```bash
pip install Flask Flask-SocketIO python-socketio
```

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/03_flask_monitoring_dashboard.py
```

Then open http://localhost:5000 in your browser.

**Key Concepts:**
- Flask web application architecture
- WebSocket integration with Flask-SocketIO
- REST API design patterns
- Production web app structure
- Real-time dashboard updates

### 03_distributed_workers.py
**Distributed Worker Processes**

Demonstrates multi-machine worker deployment patterns:
- Network-accessible shared queue database
- Unique worker identification across machines
- Concurrent processing across distributed workers
- Shared filesystem requirements (NFS/SMB)

**Note:** This example requires a shared filesystem mount at `/shared/nfs/`
For local testing, modify the `db_path` to use a local directory.

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/03_distributed_workers.py
```

**Key Concepts:**
- Distributed worker architecture
- Shared database access
- Worker identification and coordination
- Network filesystem requirements

### 04_run_strategies.py
**Advanced Retry Patterns**

Implements sophisticated retry strategies with exponential backoff:
- Exponential backoff retry logic
- Custom retry policies per job
- Failure simulation and recovery
- Delay-based job scheduling

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/04_run_strategies.py
```

**Key Concepts:**
- Exponential backoff algorithms
- Custom retry policies
- Job failure simulation
- Delay-based scheduling

### 05_dag_visualization.py
**DAG Workflow Visualization**

Generates visual representations of complex job dependencies:
- Complex DAG creation with parallel branches
- Mermaid diagram generation
- Dependency visualization
- Workflow structure analysis

**Run:**
```bash
cd /home/pingu/github/queuack
PYTHONPATH=/home/pingu/github/queuack python3 examples/05_advanced/05_dag_visualization.py
```

**Key Concepts:**
- DAG (Directed Acyclic Graph) workflows
- Mermaid diagram generation
- Complex dependency patterns
- Workflow visualization

## Common Setup

All examples require:
- Python 3.8+
- Queuack package (installed via `pip install -e .` or PYTHONPATH)
- For web examples: Chart.js (loaded from CDN)

## Running Examples

1. Ensure Queuack is installed or PYTHONPATH is set:
   ```bash
   export PYTHONPATH=/path/to/queuack:$PYTHONPATH
   # OR
   pip install -e .
   ```

2. Run any example:
   ```bash
   python3 examples/05_advanced/XX_example_name.py
   ```

3. For web-based examples, open the displayed URL in your browser

## Learning Path

Start with:
1. `01_custom_backpressure.py` - Learn backpressure patterns
2. `02_monitoring_dashboard.py` - Built-in monitoring
3. `03_flask_monitoring_dashboard.py` - Production web integration
4. `03_distributed_workers.py` - Distributed processing
5. `04_run_strategies.py` - Advanced retry patterns
6. `05_dag_visualization.py` - Complex workflow visualization

Each example builds on the previous concepts while introducing new patterns for advanced queue management, monitoring, and distributed processing.