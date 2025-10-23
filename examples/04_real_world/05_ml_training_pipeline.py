"""
ML Training Pipeline: Model Development and Deployment

This example demonstrates a complete machine learning training pipeline that
loads data, preprocesses it, trains multiple models in parallel, evaluates
them, and deploys the best performing model. This represents modern MLOps
workflows.

ML Pipeline Flow:
   Load Data → Preprocess → Split → Train Models → Evaluate → Deploy
     ↓          ↓           ↓         ↓            ↓         ↓
  (Raw)     (Clean)     (Sets)   (Parallel)    (Metrics)  (Production)

Key Components:
- Data Loading: Ingest training data from various sources
- Preprocessing: Clean, normalize, and feature engineer data
- Model Training: Train multiple algorithms in parallel
- Evaluation: Compare model performance on validation data
- Deployment: Promote best model to production environment

Real-world Use Cases:
- Automated model retraining (continuous learning systems)
- A/B testing frameworks (compare multiple model versions)
- Hyperparameter optimization (grid search across configurations)
- Ensemble learning (combine predictions from multiple models)
- Model monitoring (track performance and trigger retraining)

Queuack Features Demonstrated:
- Complex DAG structures with parallel branches
- Conditional execution (ANY mode for deployment)
- Timeout handling for long-running training jobs
- Result-based decision making in workflows
- Scalable parallel model training

Advanced Topics:
- Model selection: Choosing best algorithm automatically
- Parallel experimentation: Training multiple models concurrently
- Performance optimization: Resource management for ML workloads
- Continuous deployment: Automated model promotion
- Experiment tracking: Monitoring training metrics and results

# Difficulty: advanced
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("ml")
queue = DuckQueue(db_path)


def load_dataset(path: str):
    """Load training data."""
    print(f"Loading dataset from {path}...")
    return {"samples": 10000, "features": 50}


def preprocess_data(data: dict):
    """Clean and normalize data."""
    print("Preprocessing data...")
    return {**data, "normalized": True}


def split_data(data: dict):
    """Split into train/validation/test."""
    return {
        "train": data["samples"] * 0.7,
        "val": data["samples"] * 0.15,
        "test": data["samples"] * 0.15,
    }


def train_model(data: dict, model_type: str):
    """Train ML model."""
    print(f"Training {model_type} model...")
    return {"model": model_type, "accuracy": 0.92}


def evaluate_model(model: dict):
    """Evaluate on test set."""
    print(f"Evaluating {model['model']}...")
    return {**model, "test_accuracy": 0.89}


def deploy_model(model: dict):
    """Deploy best model."""
    print(f"Deploying {model['model']} to production...")
    return "DEPLOYED"


with queue.dag("ml_pipeline") as dag:
    load = dag.enqueue(load_dataset, args=("s3://data/training.csv",), name="load")

    preprocess = dag.enqueue(preprocess_data, name="preprocess", depends_on="load")

    split = dag.enqueue(split_data, name="split", depends_on="preprocess")

    # Train multiple models in parallel
    models = []
    for model_type in ["random_forest", "xgboost", "neural_net"]:
        train = dag.enqueue(
            train_model,
            kwargs={"model_type": model_type},
            name=f"train_{model_type}",
            depends_on="split",
            timeout_seconds=3600,  # 1 hour timeout
        )

        eval = dag.enqueue(
            evaluate_model, name=f"eval_{model_type}", depends_on=f"train_{model_type}"
        )
        models.append(f"eval_{model_type}")

    # Deploy best model (ANY mode: first to finish)
    deploy = dag.enqueue(
        deploy_model, name="deploy", depends_on=models, dependency_mode="any"
    )
