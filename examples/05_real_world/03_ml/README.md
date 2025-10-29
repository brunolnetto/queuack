# MLOps Examples with Queuack

**Replace Airflow, MLflow, and Kubeflow with simple Python + DuckDB**

These examples demonstrate how Queuack simplifies ML engineering workflows without the operational overhead of traditional MLOps platforms.

## 🎯 Why Queuack for MLOps?

### Traditional MLOps Stack (Complex)
```
Airflow (orchestration) → 2 GB RAM, Kubernetes cluster
MLflow (experiment tracking) → Separate server + database
Kubeflow (pipelines) → Full K8s cluster
Ray/Dask (parallel training) → Cluster management
```
**Total:** Significant infrastructure overhead, complex setup

### Queuack MLOps Stack (Simple)
```
Queuack → 50 MB RAM, single SQLite file
```
**Total:** Zero infrastructure, works on laptop

---

## 📁 Examples

### 01_hyperparameter_tuning.py
**Parallel hyperparameter search without Ray/MLflow**
- Parallel training (4-16 workers)
- Automatic result persistence
- Easy result querying with SQL
- No MLflow server needed
- Works on laptop for development

### 02_ml_pipeline.py
**Complete ML pipeline without Airflow/Kubeflow**
- DAG-based orchestration
- Data validation gates
- Automatic retries
- State persistence
- Progress monitoring
- Deployment automation

### 04_sklearn_classification.py
**Scikit-learn binary classification pipeline**
- Data loading, preprocessing, feature engineering
- Model training with cross-validation
- Model evaluation and selection
- Production predictions

### 05_ml_training_pipeline.py
**ML training pipeline: model development and deployment**
- Loads data, preprocesses, trains multiple models in parallel
- Evaluates and deploys the best model
- Demonstrates modern MLOps workflows

### 05_sklearn_ensemble.py
**Scikit-learn ensemble learning pipeline**
- Parallel training of diverse algorithms
- Ensemble model creation (voting, stacking)
- Meta-model training and deployment

### 06_mlflow_experiments.py
**MLflow + Queuack: experiment tracking integration**
- Parallel experiment tracking
- MLflow run management and model registry
- Hyperparameter logging and metric comparison

### 07_mlflow_model_registry.py
**MLflow model registry integration**
- (Template/example for model registry usage)

### 08_dvc_data_versioning.py
**DVC data versioning integration**
- (Template/example for DVC usage in ML pipelines)

### 09_pytorch_mlflow_dvc_complete.py
**PyTorch + MLflow + DVC: complete MLOps pipeline**
- (Template/example for full-stack MLOps with Queuack)

## 🚀 Running Examples

```bash
# Example 1: Hyperparameter search
python examples/04_real_world/03_ml/01_hyperparameter_tuning.py

# Example 2: Complete ML pipeline
python examples/04_real_world/03_ml/02_ml_pipeline.py

# Query results with SQL
sqlite3 experiments.db "SELECT * FROM jobs WHERE status='done' ORDER BY result DESC LIMIT 10"
```

---

## 💡 Common ML Workflows

### 1. Experiment Tracking

**Traditional (MLflow):**
```python
import mlflow

mlflow.start_run()
mlflow.log_param("learning_rate", 0.01)
mlflow.log_metric("accuracy", 0.95)
mlflow.end_run()

# Requires: MLflow server, database, authentication
```

**Queuack:**
```python
from queuack import DuckQueue

queue = DuckQueue("experiments.db")
queue.enqueue(train_model, args=({"lr": 0.01},))

# Results in SQLite, query with SQL
# No server needed
```

---

### 2. Parallel Training

**Traditional (Ray):**
```python
import ray

ray.init()  # Requires Ray cluster

@ray.remote
def train(params):
    return model.fit(params)

# Requires: Ray cluster setup
```

**Queuack:**
```python
from queuack import DuckQueue

queue = DuckQueue(":memory:")

for params in param_grid:
    queue.enqueue(train_model, args=(params,))

# Workers automatically parallelize
# No cluster needed
```

---

### 3. Pipeline Orchestration

**Traditional (Airflow):**
```python
from airflow import DAG
from airflow.operators.python import PythonOperator

# Requires: Airflow scheduler, webserver, database
# Complex YAML/Python configuration
```

**Queuack:**
```python
from queuack import DAG

dag = DAG("pipeline")
dag.add_node(extract, name="extract")
dag.add_node(transform, name="transform", depends_on=["extract"])
dag.execute()

# Just Python functions
# No infrastructure
```

---

## 📊 Performance Comparison

### Hyperparameter Search (54 combinations)

| Approach | Time | Infrastructure |
|----------|------|----------------|
| Sequential | ~27s | None |
| Queuack (4 workers) | ~7s | None |
| Ray (4 workers) | ~7s | Ray cluster |
| MLflow + Airflow | ~8s | Multiple servers |

**Queuack wins:** Same performance, zero infrastructure

---

## 🎓 Best Practices

### 1. Start Simple
Begin with Queuack for development:
- Test pipelines locally
- Iterate quickly without infrastructure
- Use same code in production

### 2. When to Scale Up
Consider traditional MLOps tools when:
- Distributed training across 100+ machines
- Real-time model serving (< 10ms latency)
- Complex workflow UI needed
- Multi-tenant isolation required

### 3. Hybrid Approach
Use Queuack + specialized tools:
- Queuack: Pipeline orchestration
- MLflow: Model registry (if needed)
- Seldon/TorchServe: Model serving

---

## 🔧 Integration with ML Frameworks

### scikit-learn
```python
from queuack import DuckQueue
from sklearn.ensemble import RandomForestClassifier

def train_rf(params):
    model = RandomForestClassifier(**params)
    model.fit(X_train, y_train)
    return model.score(X_test, y_test)

queue = DuckQueue("sklearn_experiments.db")
for params in param_grid:
    queue.enqueue(train_rf, args=(params,))
```

### PyTorch
```python
from queuack import DuckQueue, async_task
import torch

@async_task
async def train_pytorch(config):
    model = create_model(config)
    # Training loop
    for epoch in range(config['epochs']):
        train_one_epoch(model)
    return evaluate(model)

queue = DuckQueue("pytorch_experiments.db")
for config in configs:
    queue.enqueue(train_pytorch, args=(config,))
```

### TensorFlow
```python
from queuack import DuckQueue
import tensorflow as tf

def train_tf(params):
    model = create_tf_model(params)
    model.compile(optimizer='adam', loss='mse')
    history = model.fit(X_train, y_train, epochs=10)
    return model.evaluate(X_test, y_test)

queue = DuckQueue("tf_experiments.db")
for params in param_grid:
    queue.enqueue(train_tf, args=(params,))
```

---

## 📚 Additional Resources

- [Main README](../../README.md) - Full Queuack documentation
- [Basic Examples](../01_basic/) - Learn Queuack fundamentals
- [Real-world Examples](../04_real_world/) - More production patterns
- [Benchmarks](../../benchmarks/) - Performance comparisons

---

## 🤝 Contributing

Have ML use cases we should cover? Open an issue or PR!

Common requests:
- Model drift detection
- Feature store integration
- AutoML pipelines
- Multi-model ensembles
- Online learning
- Federated learning

---

**Made with 🦆 and ❤️ for ML engineers tired of K8s**
