# DAG Workflow Examples

Master complex workflows with dependencies, parallel execution, and conditional logic.

## Examples

- `01_linear_pipeline.py` - Simple A → B → C pipeline
- `02_fan_out_fan_in.py` - Parallel processing with synchronization
- `03_conditional_execution.py` - OR-based dependencies (ANY mode)
- `04_diamond_dependency.py` - Diamond pattern synchronization
- `05_external_dependencies.py` - Reference external jobs
- `06_subdag.py` - Reusable sub-DAGs

## Quick Start

```python
from queuack import DAG, DuckQueue

dag = DAG("pipeline", queue=DuckQueue(":memory:"))
dag.add_node(extract, name="extract")
dag.add_node(transform, name="transform", upstream=["extract"])
dag.add_node(load, name="load", upstream=["transform"])
dag.execute()
```

See [main README](../../README.md) for more details.
