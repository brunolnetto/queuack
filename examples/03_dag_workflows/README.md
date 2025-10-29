# DAG Workflow Examples

Master complex workflows with dependencies, parallel execution, and conditional logic.

## Examples

### 01_linear_pipeline.py
**Simple A → B → C pipeline**
- Basic linear DAG.

### 02_fan_out_fan_in.py
**Parallel processing with synchronization**
- Fan-out/fan-in pattern.

### 03_conditional_execution.py
**OR-based dependencies (ANY mode)**
- Run when any parent completes.

### 04_diamond_dependency.py
**Diamond pattern synchronization**
- Classic diamond-shaped DAG.

### 05_external_dependencies.py
**Reference external jobs**
- DAGs with dependencies outside the current workflow.

### 06_subdag_basic.py
**Basic sub-DAG**
- Reusable sub-workflows.

### 07_subdag_nested.py
**Nested sub-DAGs**
- Sub-DAGs within sub-DAGs (advanced).

### 08_debugging_dags.py
**Debugging DAGs**
- Inspect and debug DAG runs.

### 09_error_recovery.py
**Error recovery**
- Handle and recover from DAG failures.

### 10_dynamics_dag.py
**Dynamic DAG**
- Build DAGs programmatically at runtime.

### 11_context_aware_dags.py
**Context-aware tasks**
- Use TaskContext to access parent results.

### 12_branching_workflows.py
**Branching workflows**
- Conditional execution paths.

### 13_dag_visualization.py
**DAG visualization**
- Export and visualize DAG structure.

## Quick Start

```python
from queuack import DAG, DuckQueue

dag = DAG("pipeline", queue=DuckQueue(":memory:"))
dag.add_node(extract, name="extract")
dag.add_node(transform, name="transform", depends_on=["extract"])
dag.add_node(load, name="load", depends_on=["transform"])
dag.execute()
```

See [main README](../../README.md) for more details.
