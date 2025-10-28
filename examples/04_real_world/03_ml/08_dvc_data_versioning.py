#!/usr/bin/env python3
"""
DVC + Queuack: Data Version Control Integration

Demonstrates how to combine Queuack orchestration with DVC data versioning:
- DVC handles: Data versioning, remote storage, reproducibility
- Queuack handles: Pipeline orchestration, parallel processing, retries

This shows a complete MLOps workflow with data versioning.

# Difficulty: advanced

Requirements:
    pip install dvc scikit-learn pandas

Shows:
- Data versioning with DVC
- Reproducible ML pipelines
- Dataset tracking across experiments
- Model training with versioned data
- Pipeline caching and reuse
"""

import sys
import os
import time
import json
import subprocess
from pathlib import Path
from typing import Dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from queuack import DAG, TaskContext, DuckQueue, generator_task, StreamReader, StreamWriter


# ==============================================================================
# Setup DVC Repository
# ==============================================================================

def setup_dvc_repo():
    """
    Initialize DVC repository for data versioning.
    
    In production: Use real remote storage (S3, GCS, Azure)
    For this example: Use local remote
    """
    print("\n📦 Setting up DVC repository...")
    
    # Create DVC directories
    Path("data").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)
    Path(".dvc_remote").mkdir(exist_ok=True)
    
    # Initialize DVC if not already done
    if not Path(".dvc").exists():
        subprocess.run(["dvc", "init"], check=True)
        print("   ✅ DVC initialized")
    
    # Configure local remote storage
    subprocess.run([
        "dvc", "remote", "add", "-d", "-f", "local_remote", ".dvc_remote"
    ], check=False)  # Ignore error if already exists
    
    print("   ✅ DVC remote configured")
    print("   📁 Data: ./data (tracked by DVC)")
    print("   📁 Models: ./models (tracked by DVC)")
    print("   📁 Remote: ./.dvc_remote (local cache)")


# ==============================================================================
# Step 1: Generate and Version Dataset
# ==============================================================================

def generate_dataset(version: str = "v1") -> Dict:
    """
    Generate dataset and version with DVC.
    
    In production: Replace with actual data collection/ETL.
    """
    print(f"\n📊 Step 1: Generating dataset (version {version})")
    
    import pandas as pd
    import numpy as np
    
    np.random.seed(42 if version == "v1" else 123)
    
    # Generate synthetic data
    n_samples = 10000 if version == "v1" else 15000  # v2 has more data
    
    data = {
        'feature_1': np.random.randn(n_samples),
        'feature_2': np.random.randn(n_samples),
        'feature_3': np.random.randn(n_samples),
        'feature_4': np.random.uniform(0, 100, n_samples),
        'feature_5': np.random.randint(0, 10, n_samples),
    }
    
    # Target variable
    data['target'] = (
        0.5 * data['feature_1'] +
        0.3 * data['feature_2'] -
        0.2 * data['feature_3'] +
        np.random.randn(n_samples) * 0.1
    )
    
    df = pd.DataFrame(data)
    
    # Save to CSV
    data_path = f"data/dataset_{version}.csv"
    df.to_csv(data_path, index=False)
    
    print(f"   💾 Saved: {data_path} ({n_samples:,} samples)")
    
    # Add to DVC tracking
    print("   📦 Tracking with DVC...")
    subprocess.run(["dvc", "add", data_path], check=True)
    
    # Commit DVC metadata
    subprocess.run(["git", "add", f"{data_path}.dvc", ".gitignore"], check=False)
    subprocess.run([
        "git", "commit", "-m", f"Add dataset {version}"
    ], check=False)
    
    # Push to DVC remote
    subprocess.run(["dvc", "push"], check=True)
    
    print(f"   ✅ Dataset {version} versioned and pushed")
    
    return {
        'version': version,
        'path': data_path,
        'n_samples': n_samples,
        'n_features': 5
    }


# ==============================================================================
# Step 2: Load Versioned Dataset
# ==============================================================================

def load_versioned_data(context: TaskContext, version: str = "v1") -> Dict:
    """
    Load a specific version of the dataset from DVC.
    
    This demonstrates reproducibility - can always get exact data version.
    """
    print(f"\n📥 Step 2: Loading versioned data ({version})")
    
    dataset_info = context.upstream("generate")
    data_path = dataset_info['path']
    
    # In production, you would:
    # 1. Checkout specific DVC version: dvc checkout data/dataset.csv.dvc@v1
    # 2. Pull from remote: dvc pull
    
    # For this example, data is already available locally
    subprocess.run(["dvc", "pull", data_path], check=False)
    
    import pandas as pd
    df = pd.read_csv(data_path)
    
    print(f"   ✅ Loaded: {data_path}")
    print(f"   📊 Shape: {df.shape}")
    print(f"   🔢 Columns: {list(df.columns)}")
    
    return {
        'version': version,
        'path': data_path,
        'n_samples': len(df),
        'n_features': len(df.columns) - 1,  # Exclude target
        'columns': list(df.columns)
    }


# ==============================================================================
# Step 3: Preprocess Data
# ==============================================================================

@generator_task(format="parquet")
def preprocess_data(context: TaskContext):
    """
    Preprocess versioned data.
    
    Outputs are also versioned via DVC.
    """
    print("\n🔧 Step 3: Preprocessing data")
    
    data_info = context.upstream("load")
    
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    
    df = pd.read_csv(data_info['path'])
    
    # Split features and target
    X = df.drop('target', axis=1)
    y = df['target']
    
    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Yield preprocessed records
    for i in range(len(X_scaled)):
        yield {
            'features': X_scaled[i].tolist(),
            'target': float(y.iloc[i])
        }


# ==============================================================================
# Step 4: Train Model with Versioned Data
# ==============================================================================

def train_model(context: TaskContext) -> Dict:
    """
    Train model on versioned, preprocessed data.
    
    Model is also versioned with DVC for reproducibility.
    """
    print("\n🎯 Step 4: Training model")
    
    data_info = context.upstream("load")
    preprocessed_path = context.upstream("preprocess")
    
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_squared_error, r2_score
    import pickle
    
    # Load preprocessed data
    reader = StreamReader(preprocessed_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Train model
    model = Ridge(alpha=1.0)
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print(f"   📊 MSE: {mse:.4f}")
    print(f"   📊 R²: {r2:.4f}")
    
    # Save model
    data_version = data_info['version']
    model_path = f"models/model_{data_version}.pkl"
    
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    
    print(f"   💾 Saved: {model_path}")
    
    # Version model with DVC
    print("   📦 Versioning model with DVC...")
    subprocess.run(["dvc", "add", model_path], check=True)
    
    # Commit DVC metadata
    subprocess.run(["git", "add", f"{model_path}.dvc", ".gitignore"], check=False)
    subprocess.run([
        "git", "commit", "-m", f"Add model trained on {data_version}"
    ], check=False)
    
    # Push to DVC remote
    subprocess.run(["dvc", "push"], check=True)
    
    print(f"   ✅ Model versioned and pushed")
    
    return {
        'data_version': data_version,
        'model_path': model_path,
        'mse': mse,
        'r2': r2,
        'n_train_samples': len(X_train),
        'n_test_samples': len(X_test)
    }


# ==============================================================================
# Step 5: Model Registry and Metadata
# ==============================================================================

def register_model(context: TaskContext) -> Dict:
    """
    Register model with metadata linking to data version.
    
    This creates an audit trail: model → data version → exact dataset.
    """
    print("\n📋 Step 5: Registering model")
    
    model_info = context.upstream("train")
    data_info = context.upstream("load")
    
    # Create model registry entry
    registry = {
        'model_path': model_info['model_path'],
        'data_version': model_info['data_version'],
        'data_path': data_info['path'],
        'metrics': {
            'mse': model_info['mse'],
            'r2': model_info['r2']
        },
        'training_info': {
            'n_train_samples': model_info['n_train_samples'],
            'n_test_samples': model_info['n_test_samples']
        },
        'dvc_metadata': {
            'data_dvc': f"{data_info['path']}.dvc",
            'model_dvc': f"{model_info['model_path']}.dvc"
        },
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Save registry
    registry_path = "models/model_registry.json"
    
    # Load existing registry or create new
    if Path(registry_path).exists():
        with open(registry_path, 'r') as f:
            existing_registry = json.load(f)
    else:
        existing_registry = {'models': []}
    
    existing_registry['models'].append(registry)
    
    with open(registry_path, 'w') as f:
        json.dump(existing_registry, f, indent=2)
    
    print(f"   ✅ Registered model: {model_info['model_path']}")
    print(f"   🔗 Linked to data: {data_info['path']}")
    print(f"   📊 Metrics: MSE={model_info['mse']:.4f}, R²={model_info['r2']:.4f}")
    
    return registry


# ==============================================================================
# Main Pipeline
# ==============================================================================

def main():
    """Execute DVC + Queuack data versioning pipeline."""
    print("🦆" * 35)
    print("  DVC + Queuack Integration")
    print("  Data Versioning + ML Pipeline Orchestration")
    print("🦆" * 35)
    
    # Setup DVC
    setup_dvc_repo()
    
    # Create Queuack pipeline
    queue = DuckQueue(db_path="dvc_pipeline.db")
    dag = DAG("dvc_ml_pipeline", queue=queue)
    
    # Build pipeline
    print("\n🔄 Building versioned ML pipeline...")
    
    version = "v1"  # Change to "v2" to train on different data version
    
    dag.add_node(
        generate_dataset,
        kwargs={'version': version},
        name="generate"
    )
    
    dag.add_node(
        load_versioned_data,
        kwargs={'version': version},
        name="load",
        depends_on=["generate"]
    )
    
    dag.add_node(
        preprocess_data,
        name="preprocess",
        depends_on=["load"]
    )
    
    dag.add_node(
        train_model,
        name="train",
        depends_on=["load", "preprocess"]
    )
    
    dag.add_node(
        register_model,
        name="register",
        depends_on=["load", "train"]
    )
    
    # Execute
    start = time.perf_counter()
    dag.execute()
    duration = time.perf_counter() - start
    
    print("\n" + "=" * 70)
    print("✅ PIPELINE COMPLETED")
    print("=" * 70)
    print(f"   Duration: {duration:.2f}s")
    print(f"   Queuack DB: dvc_pipeline.db")
    print(f"   DVC Remote: ./.dvc_remote")
    print(f"   Model Registry: models/model_registry.json")
    
    print("\n💡 DVC Commands:")
    print("""
   # View tracked files
   dvc list . data
   
   # View file history
   git log data/dataset_v1.csv.dvc
   
   # Checkout specific version
   git checkout <commit> data/dataset_v1.csv.dvc
   dvc checkout
   
   # Compare data versions
   dvc diff
   
   # Pull data from remote
   dvc pull
   
   # Push data to remote
   dvc push
    """)
    
    queue.close()
    
    print("\n🔍 Why Combine Queuack + DVC?")
    print("""
   DVC provides:
   ✅ Data version control (like Git for data)
   ✅ Remote storage integration (S3, GCS, Azure)
   ✅ Reproducibility (exact data for each experiment)
   ✅ Large file tracking (datasets, models)
   ✅ Data pipeline caching
   
   Queuack provides:
   ✅ Pipeline orchestration
   ✅ Parallel task execution
   ✅ Automatic retries
   ✅ Job tracking
   ✅ Crash recovery
   
   Together:
   🚀 Reproducible ML workflows
   🚀 Version everything (data + code + models)
   🚀 Audit trail for compliance
   🚀 Easy collaboration across teams
   🚀 No Airflow/Kubeflow complexity
    """)
    
    print("\n📚 Production Use Cases:")
    print("""
   1. Regulatory Compliance
      - Track exact data used for each model
      - Audit trail for financial/healthcare models
      
   2. Model Debugging
      - Reproduce exact training environment
      - Compare model performance across data versions
      
   3. A/B Testing
      - Test models trained on different data versions
      - Compare results scientifically
      
   4. Continuous Training
      - Version data snapshots daily/weekly
      - Track model performance over time
      
   5. Team Collaboration
      - Share exact datasets across team
      - Reproducible experiments for everyone
    """)
    
    print("\n🎯 Next Steps:")
    print("""
   1. Configure real remote storage (S3/GCS)
   2. Add data validation and drift detection
   3. Implement model monitoring
   4. Set up automated retraining triggers
   5. Add model deployment pipeline
   6. Integrate with MLflow for experiment tracking
    """)


if __name__ == "__main__":
    main()