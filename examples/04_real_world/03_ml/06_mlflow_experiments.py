#!/usr/bin/env python3
"""
MLflow + Queuack: Experiment Tracking Integration

Demonstrates how to combine Queuack orchestration with MLflow experiment tracking:
- Queuack handles: Job orchestration, parallelization, retries
- MLflow handles: Experiment tracking, model registry, versioning

This shows how Queuack complements (not replaces) MLflow.

# Difficulty: intermediate

Requirements:
    pip install mlflow scikit-learn

Shows:
- Parallel experiment tracking
- MLflow run management
- Model registry integration
- Hyperparameter logging
- Metric comparison
"""

import sys
import time
from pathlib import Path
from typing import Dict
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from queuack import DAG, TaskContext, DuckQueue


# ==============================================================================
# Setup MLflow
# ==============================================================================

def setup_mlflow():
    """Configure MLflow tracking."""
    import mlflow
    
    # Set tracking URI (use local directory for this example)
    mlflow.set_tracking_uri("file:./mlruns")
    
    # Create or get experiment
    experiment_name = "queuack_sklearn_experiments"
    try:
        experiment_id = mlflow.create_experiment(experiment_name)
    except Exception:
        experiment_id = mlflow.get_experiment_by_name(experiment_name).experiment_id
    
    mlflow.set_experiment(experiment_name)
    
    print(f"\n📊 MLflow Tracking URI: file:./mlruns")
    print(f"📊 Experiment: {experiment_name}")
    
    return experiment_id


# ==============================================================================
# Training Functions with MLflow Tracking
# ==============================================================================

def train_with_mlflow(params: Dict) -> Dict:
    """
    Train a model and track everything with MLflow.
    
    This is the key integration point: Queuack orchestrates,
    MLflow tracks the experiment.
    """
    import mlflow
    import mlflow.sklearn
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.datasets import make_classification
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    import numpy as np
    
    # Generate synthetic dataset
    X, y = make_classification(
        n_samples=1000,
        n_features=20,
        n_informative=15,
        n_redundant=5,
        random_state=42
    )
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Start MLflow run
    with mlflow.start_run(run_name=f"rf_{params['n_estimators']}_{params['max_depth']}"):
        # Log parameters
        mlflow.log_params(params)
        
        # Train model
        model = RandomForestClassifier(**params, random_state=42)
        model.fit(X_train, y_train)
        
        # Make predictions
        y_pred = model.predict(X_test)
        
        # Calculate metrics
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred, average='binary'),
            'recall': recall_score(y_test, y_pred, average='binary'),
            'f1': f1_score(y_test, y_pred, average='binary')
        }
        
        # Log metrics
        mlflow.log_metrics(metrics)
        
        # Log model
        mlflow.sklearn.log_model(model, "model")
        
        # Log feature importances as artifact
        feature_importance = {
            f"feature_{i}": float(imp) 
            for i, imp in enumerate(model.feature_importances_)
        }
        
        with open("feature_importance.json", "w") as f:
            json.dump(feature_importance, f, indent=2)
        mlflow.log_artifact("feature_importance.json")
        
        # Get run ID for later retrieval
        run_id = mlflow.active_run().info.run_id
        
        print(f"   ✅ Run {run_id[:8]}: Accuracy={metrics['accuracy']:.4f}")
        
        return {
            'params': params,
            'metrics': metrics,
            'run_id': run_id,
            'model_uri': f"runs:/{run_id}/model"
        }


# ==============================================================================
# Parallel Hyperparameter Search with MLflow
# ==============================================================================

def run_experiment_1(context: TaskContext) -> Dict:
    """Experiment 1: n_estimators=50, max_depth=5"""
    return train_with_mlflow({
        'n_estimators': 50,
        'max_depth': 5
    })


def run_experiment_2(context: TaskContext) -> Dict:
    """Experiment 2: n_estimators=100, max_depth=5"""
    return train_with_mlflow({
        'n_estimators': 100,
        'max_depth': 5
    })


def run_experiment_3(context: TaskContext) -> Dict:
    """Experiment 3: n_estimators=50, max_depth=10"""
    return train_with_mlflow({
        'n_estimators': 50,
        'max_depth': 10
    })


def run_experiment_4(context: TaskContext) -> Dict:
    """Experiment 4: n_estimators=100, max_depth=10"""
    return train_with_mlflow({
        'n_estimators': 100,
        'max_depth': 10
    })


def run_experiment_5(context: TaskContext) -> Dict:
    """Experiment 5: n_estimators=150, max_depth=10"""
    return train_with_mlflow({
        'n_estimators': 150,
        'max_depth': 10
    })


def run_experiment_6(context: TaskContext) -> Dict:
    """Experiment 6: n_estimators=100, max_depth=15"""
    return train_with_mlflow({
        'n_estimators': 100,
        'max_depth': 15
    })


# ==============================================================================
# Analyze Results
# ==============================================================================

def analyze_experiments(context: TaskContext) -> Dict:
    """
    Analyze all experiments and select the best model.
    
    Uses context.upstream_all() to get all experiment results.
    """
    import mlflow
    
    print("\n📊 Analyzing Experiments")
    
    # Get all experiment results from upstream tasks
    all_results = context.upstream_all()
    
    print(f"\n   Comparing {len(all_results)} experiments:")
    
    # Sort by accuracy
    sorted_results = sorted(
        all_results.items(),
        key=lambda x: x[1]['metrics']['accuracy'],
        reverse=True
    )
    
    # Display results
    for i, (name, result) in enumerate(sorted_results, 1):
        params = result['params']
        metrics = result['metrics']
        print(f"   {i}. Run {result['run_id'][:8]}: "
              f"n_est={params['n_estimators']}, depth={params['max_depth']} "
              f"→ Acc={metrics['accuracy']:.4f}")
    
    # Get best experiment
    best_name, best_result = sorted_results[0]
    
    print(f"\n   🏆 Best Model: Run {best_result['run_id'][:8]}")
    print(f"      Parameters: {best_result['params']}")
    print(f"      Accuracy: {best_result['metrics']['accuracy']:.4f}")
    print(f"      F1 Score: {best_result['metrics']['f1']:.4f}")
    
    # Register best model in MLflow Model Registry
    model_name = "sklearn_rf_classifier"
    
    try:
        # Register model
        model_uri = best_result['model_uri']
        model_version = mlflow.register_model(model_uri, model_name)
        
        print(f"\n   📦 Registered model: {model_name}")
        print(f"      Version: {model_version.version}")
        print(f"      Run ID: {best_result['run_id']}")
        
        # Transition to staging
        client = mlflow.tracking.MlflowClient()
        client.transition_model_version_stage(
            name=model_name,
            version=model_version.version,
            stage="Staging"
        )
        
        print(f"   ✅ Transitioned to Staging")
        
    except Exception as e:
        print(f"   ⚠️  Could not register model: {e}")
    
    return {
        'best_run_id': best_result['run_id'],
        'best_params': best_result['params'],
        'best_metrics': best_result['metrics'],
        'all_results': {name: res['metrics']['accuracy'] for name, res in all_results.items()}
    }


# ==============================================================================
# Main Pipeline
# ==============================================================================

def main():
    """Execute MLflow + Queuack experiment tracking."""
    print("🦆" * 35)
    print("  MLflow + Queuack Integration")
    print("  Orchestration + Experiment Tracking")
    print("🦆" * 35)
    
    # Setup MLflow
    setup_mlflow()
    
    # Create Queuack pipeline
    queue = DuckQueue(db_path="mlflow_experiments.db")
    dag = DAG("mlflow_hyperparam_search", queue=queue)
    
    # Run experiments in parallel
    print("\n🔄 Running 6 experiments in parallel...")
    
    dag.add_node(run_experiment_1, name="exp_1")
    dag.add_node(run_experiment_2, name="exp_2")
    dag.add_node(run_experiment_3, name="exp_3")
    dag.add_node(run_experiment_4, name="exp_4")
    dag.add_node(run_experiment_5, name="exp_5")
    dag.add_node(run_experiment_6, name="exp_6")
    
    # Analyze after all experiments complete
    dag.add_node(
        analyze_experiments,
        name="analyze",
        depends_on=["exp_1", "exp_2", "exp_3", "exp_4", "exp_5", "exp_6"]
    )
    
    # Execute
    start = time.perf_counter()
    dag.execute()
    duration = time.perf_counter() - start
    
    print("\n" + "=" * 70)
    print("✅ EXPERIMENT SUITE COMPLETED")
    print("=" * 70)
    print(f"   Duration: {duration:.2f}s")
    print(f"   Queuack DB: mlflow_experiments.db")
    print(f"   MLflow Tracking: ./mlruns")
    
    print("\n💡 View Results:")
    print("   1. MLflow UI: mlflow ui")
    print("   2. Open: http://localhost:5000")
    print("   3. Compare runs, view metrics, download models")
    
    queue.close()
    
    print("\n🔍 Why Combine Queuack + MLflow?")
    print("""
   Queuack provides:
   ✅ Parallel experiment execution
   ✅ Job orchestration and retries
   ✅ DAG-based workflows
   ✅ Crash recovery
   ✅ Simple local development
   
   MLflow provides:
   ✅ Experiment tracking UI
   ✅ Model registry
   ✅ Model versioning
   ✅ Artifact storage
   ✅ Model deployment integration
   
   Together:
   🚀 Best of both worlds - simple orchestration + powerful tracking
   🚀 No Kubeflow/Airflow complexity
   🚀 Production-ready experiment management
    """)
    
    print("\n📚 Next Steps:")
    print("""
   1. Replace synthetic data with real datasets
   2. Add more sophisticated hyperparameter grids
   3. Implement Bayesian optimization
   4. Add model monitoring and drift detection
   5. Set up automated retraining workflows
   6. Deploy models to production endpoints
    """)


if __name__ == "__main__":
    main()