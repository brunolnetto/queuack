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
from queuack import DAG, TaskContext

db_path = create_temp_path("ml")


def load_dataset(path: str):
    """Load training data."""
    print(f"Loading dataset from {path}...")
    return {"samples": 10000, "features": 50}


def preprocess_data(context: TaskContext):
    """Clean and normalize data."""
    data = context.upstream("load")

    print("Preprocessing data...")
    return {**data, "normalized": True}

def split_data(context: TaskContext, split_ratios: dict = None):
    """Split into train/validation/test."""

    data = context.upstream("preprocess")

    train_partition_perc = split_ratios.get("train", 0.7)
    val_partition_perc = split_ratios.get("val", 0.15)
    test_partition_perc = split_ratios.get("test", 0.15)

    return {
        "train": data["samples"] * train_partition_perc,
        "val": data["samples"] * val_partition_perc,
        "test": data["samples"] * test_partition_perc,
    }


def train_model(context: TaskContext, model_type: str):
    """Train ML model."""
    data = context.upstream("split")

    print(f"Training {model_type} model...")
    return {
        "model": model_type, 
        "metrics": {
            "accuracy": 0.85 + hash(model_type) % 15 / 100
        }
    }


def evaluate_model(context: TaskContext):
    """Evaluate on test set."""

    model_type = context.get_parent_names()[0]
    model = context.upstream_or(model_type)
    
    def approval_criterium(model: dict) -> dict:
        """Evaluate model quality."""
        return model["metrics"]["accuracy"] > 0.8

    # Quality gates, metrics, etc.
    print(f"Evaluating {model['model']}...")
    return {**model, "is_valid": approval_criterium(model)}


def deploy_model(context: TaskContext):
    """Deploy best model."""
    for parent_name in context.get_parent_names():
        model = context.upstream_or(parent_name, default=None)
    
        if model is not None:
            print(f"Deploying model from {parent_name}: {model}")
            return "DEPLOYED"
            break

    return "NO MODEL TO DEPLOY"

# Define model types to train
model_types=["random_forest", "xgboost", "neural_net"]
split_ratios={"train": 0.7, "val": 0.15, "test": 0.15}
diagram_path = "ml_pipeline_mermaid.md"


with DAG("ml_pipeline") as dag:
    dag.add_node(
        load_dataset, 
        args=("s3://data/training.csv",), 
        name="load"
    )
    dag.add_node(
        preprocess_data, 
        name="preprocess", 
        depends_on=["load"]
    )
    dag.add_node(
        split_data, 
        kwargs={"split_ratios": split_ratios},
        name="split", 
        depends_on=["preprocess"])

    # Train multiple models in parallel
    models = []

    if sum(split_ratios.values()) != 1.0:
        raise ValueError("Split ratios must sum to 1.0")

    for model_type in model_types:
        dag.add_node(
            train_model,
            kwargs={"model_type": model_type},
            name=f"train_{model_type}",
            depends_on=["split"],
            timeout_seconds=3600,  # 1 hour timeout
        )

        dag.add_node(
            evaluate_model, 
            name=f"eval_{model_type}", 
            depends_on=[f"train_{model_type}"]
        )
        models.append(f"eval_{model_type}")

    # Deploy best model (ANY mode: first to finish)
    dag.add_node(
        deploy_model, 
        name="deploy", 
        depends_on=models, 
        dependency_mode="any")

    print("Submitting ML training DAG and waiting for completion...")
    dag.submit()
    dag.wait_for_completion(poll_interval=0.5)

    diagram = dag.export_mermaid()

    with open(diagram_path, "w") as f:
        f.write(diagram)

    print(f"\nDAG Execution Complete. Mermaid diagram saved to {diagram_path}")