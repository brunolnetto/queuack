#!/usr/bin/env python3
"""
Complete MLOps Stack: PyTorch + MLflow + DVC + Queuack

This example demonstrates the ultimate ML workflow combining:
- PyTorch: Deep learning framework
- MLflow: Experiment tracking and model registry
- DVC: Data version control
- Queuack: Pipeline orchestration

A production-ready ML system without Kubernetes/Airflow complexity.

# Difficulty: expert

Requirements:
    pip install torch torchvision mlflow dvc

Shows:
- End-to-end deep learning pipeline
- Data versioning with DVC
- Experiment tracking with MLflow
- Parallel training with Queuack
- Model registry and deployment
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

from queuack import DAG, TaskContext, DuckQueue


# ==============================================================================
# Setup Infrastructure
# ==============================================================================

def setup_infrastructure():
    """Initialize DVC and MLflow."""
    print("\n🛠️  Setting up MLOps infrastructure...")
    
    # Setup DVC
    Path("data").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)
    Path(".dvc_remote").mkdir(exist_ok=True)
    
    if not Path(".dvc").exists():
        subprocess.run(["dvc", "init"], check=True, capture_output=True)
    
    subprocess.run([
        "dvc", "remote", "add", "-d", "-f", "local_remote", ".dvc_remote"
    ], check=False, capture_output=True)
    
    # Setup MLflow
    import mlflow
    mlflow.set_tracking_uri("file:./mlruns")
    experiment_name = "pytorch_complete_mlops"
    
    try:
        mlflow.create_experiment(experiment_name)
    except Exception:
        pass
    
    mlflow.set_experiment(experiment_name)
    
    print("   ✅ DVC initialized: ./.dvc_remote")
    print("   ✅ MLflow initialized: ./mlruns")


# ==============================================================================
# Step 1: Generate and Version Dataset with DVC
# ==============================================================================

def create_versioned_dataset(context: TaskContext, version: str = "v1") -> Dict:
    """
    Create dataset and version with DVC.
    
    In production: Replace with real data collection.
    """
    print(f"\n📊 Step 1: Creating versioned dataset ({version})")
    
    import torch
    from torchvision import datasets, transforms
    
    # Download MNIST (simulating data collection)
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])
    
    train_dataset = datasets.MNIST(
        './data/raw',
        train=True,
        download=True,
        transform=transform
    )
    
    # Save dataset metadata
    dataset_info = {
        'version': version,
        'name': 'MNIST',
        'n_samples': len(train_dataset),
        'n_classes': 10,
        'image_size': [28, 28]
    }
    
    metadata_path = f"data/dataset_{version}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(dataset_info, f, indent=2)
    
    # Version with DVC
    subprocess.run(["dvc", "add", "data/raw"], check=True, capture_output=True)
    subprocess.run(["dvc", "add", metadata_path], check=True, capture_output=True)
    subprocess.run(["dvc", "push"], check=True, capture_output=True)
    
    print(f"   ✅ Dataset versioned: {dataset_info['n_samples']:,} samples")
    
    return dataset_info


# ==============================================================================
# Step 2: Train PyTorch Model with MLflow Tracking
# ==============================================================================

def train_pytorch_model_config1(context: TaskContext) -> Dict:
    """Train model with configuration 1."""
    return train_pytorch_model(context, config={
        'lr': 0.01,
        'batch_size': 64,
        'epochs': 3,
        'hidden_size': 128
    })


def train_pytorch_model_config2(context: TaskContext) -> Dict:
    """Train model with configuration 2."""
    return train_pytorch_model(context, config={
        'lr': 0.001,
        'batch_size': 128,
        'epochs': 3,
        'hidden_size': 256
    })


def train_pytorch_model_config3(context: TaskContext) -> Dict:
    """Train model with configuration 3."""
    return train_pytorch_model(context, config={
        'lr': 0.005,
        'batch_size': 64,
        'epochs': 3,
        'hidden_size': 256
    })


def train_pytorch_model(context: TaskContext, config: Dict) -> Dict:
    """
    Train PyTorch model with MLflow tracking.
    
    Combines:
    - DVC: Versioned data loading
    - PyTorch: Model training
    - MLflow: Experiment tracking
    """
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader
    from torchvision import datasets, transforms
    import mlflow
    import mlflow.pytorch
    
    print(f"\n🔥 Training PyTorch model (lr={config['lr']}, bs={config['batch_size']})")
    
    # Get dataset info from upstream
    dataset_info = context.upstream("dataset")
    
    # Load data
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])
    
    train_dataset = datasets.MNIST(
        './data/raw',
        train=True,
        download=False,
        transform=transform
    )
    
    test_dataset = datasets.MNIST(
        './data/raw',
        train=False,
        download=False,
        transform=transform
    )
    
    train_loader = DataLoader(
        train_dataset,
        batch_size=config['batch_size'],
        shuffle=True
    )
    
    test_loader = DataLoader(
        test_dataset,
        batch_size=1000,
        shuffle=False
    )
    
    # Define model
    class SimpleNet(nn.Module):
        def __init__(self, hidden_size):
            super().__init__()
            self.fc1 = nn.Linear(28*28, hidden_size)
            self.fc2 = nn.Linear(hidden_size, 10)
        
        def forward(self, x):
            x = x.view(-1, 28*28)
            x = torch.relu(self.fc1(x))
            x = self.fc2(x)
            return x
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = SimpleNet(config['hidden_size']).to(device)
    optimizer = optim.Adam(model.parameters(), lr=config['lr'])
    criterion = nn.CrossEntropyLoss()
    
    # Start MLflow run
    with mlflow.start_run(run_name=f"lr{config['lr']}_bs{config['batch_size']}"):
        # Log parameters
        mlflow.log_params(config)
        mlflow.log_param('data_version', dataset_info['version'])
        mlflow.log_param('device', str(device))
        
        # Training loop
        for epoch in range(config['epochs']):
            model.train()
            train_loss = 0
            
            for batch_idx, (data, target) in enumerate(train_loader):
                data, target = data.to(device), target.to(device)
                
                optimizer.zero_grad()
                output = model(data)
                loss = criterion(output, target)
                loss.backward()
                optimizer.step()
                
                train_loss += loss.item()
            
            avg_train_loss = train_loss / len(train_loader)
            
            # Evaluate
            model.eval()
            correct = 0
            test_loss = 0
            
            with torch.no_grad():
                for data, target in test_loader:
                    data, target = data.to(device), target.to(device)
                    output = model(data)
                    test_loss += criterion(output, target).item()
                    pred = output.argmax(dim=1, keepdim=True)
                    correct += pred.eq(target.view_as(pred)).sum().item()
            
            test_loss /= len(test_loader)
            accuracy = correct / len(test_dataset)
            
            # Log metrics
            mlflow.log_metrics({
                'train_loss': avg_train_loss,
                'test_loss': test_loss,
                'accuracy': accuracy
            }, step=epoch)
            
            print(f"   Epoch {epoch+1}/{config['epochs']}: "
                  f"Loss={avg_train_loss:.4f}, Acc={accuracy:.4f}")
        
        # Save model
        model_path = f"models/model_lr{config['lr']}_bs{config['batch_size']}.pth"
        torch.save(model.state_dict(), model_path)
        
        # Log model to MLflow
        mlflow.pytorch.log_model(model, "model")
        
        # Version model with DVC
        subprocess.run(["dvc", "add", model_path], check=True, capture_output=True)
        subprocess.run(["dvc", "push"], check=True, capture_output=True)
        
        run_id = mlflow.active_run().info.run_id
        
        result = {
            'config': config,
            'data_version': dataset_info['version'],
            'final_accuracy': accuracy,
            'final_loss': test_loss,
            'model_path': model_path,
            'mlflow_run_id': run_id,
            'mlflow_model_uri': f"runs:/{run_id}/model"
        }
        
        print(f"   ✅ Final Accuracy: {accuracy:.4f}")
        print(f"   📦 Model versioned with DVC")
        print(f"   📊 Run ID: {run_id[:8]}")
        
        return result


# ==============================================================================
# Step 3: Select Best Model and Register
# ==============================================================================

def select_and_register_best_model(context: TaskContext) -> Dict:
    """
    Compare all models and register the best one.
    
    Uses:
    - MLflow: Model registry
    - DVC: Model versioning
    """
    import mlflow
    
    print("\n🏆 Step 3: Selecting and registering best model")
    
    # Get all training results
    all_results = context.upstream_all()
    
    print(f"\n   Comparing {len(all_results)} models:")
    for name, result in all_results.items():
        config = result['config']
        print(f"   - lr={config['lr']}, bs={config['batch_size']}: "
              f"Acc={result['final_accuracy']:.4f}")
    
    # Select best by accuracy
    best_name = max(all_results.keys(), 
                    key=lambda k: all_results[k]['final_accuracy'])
    best_result = all_results[best_name]
    
    print(f"\n   ✅ Best Model: {best_result['config']}")
    print(f"      Accuracy: {best_result['final_accuracy']:.4f}")
    print(f"      Data Version: {best_result['data_version']}")
    
    # Register in MLflow Model Registry
    model_name = "mnist_classifier"
    
    try:
        model_version = mlflow.register_model(
            best_result['mlflow_model_uri'],
            model_name
        )
        
        print(f"\n   📦 Registered in MLflow:")
        print(f"      Model: {model_name}")
        print(f"      Version: {model_version.version}")
        
        # Transition to staging
        client = mlflow.tracking.MlflowClient()
        client.transition_model_version_stage(
            name=model_name,
            version=model_version.version,
            stage="Staging"
        )
        
        # Add description with data version
        client.update_model_version(
            name=model_name,
            version=model_version.version,
            description=f"Trained on data version {best_result['data_version']} "
                       f"with accuracy {best_result['final_accuracy']:.4f}"
        )
        
        print(f"      Stage: Staging")
        print(f"      ✅ Ready for deployment")
        
    except Exception as e:
        print(f"   ⚠️  Model registration error: {e}")
    
    # Create deployment manifest
    manifest = {
        'model_name': model_name,
        'config': best_result['config'],
        'data_version': best_result['data_version'],
        'accuracy': best_result['final_accuracy'],
        'model_path': best_result['model_path'],
        'mlflow_run_id': best_result['mlflow_run_id'],
        'dvc_tracked': True,
        'deployment_ready': True,
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open('models/deployment_manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    
    return manifest


# ==============================================================================
# Step 4: Deploy Model (Simulated)
# ==============================================================================

def deploy_model(context: TaskContext) -> Dict:
    """
    Deploy the registered model.
    
    In production: Deploy to:
    - TorchServe
    - AWS SageMaker
    - Azure ML
    - GCP Vertex AI
    """
    print("\n🚀 Step 4: Deploying model")
    
    manifest = context.upstream("register")
    
    print(f"   Model: {manifest['model_name']}")
    print(f"   Accuracy: {manifest['accuracy']:.4f}")
    print(f"   Data Version: {manifest['data_version']}")
    
    # Simulate deployment
    deployment = {
        'model_name': manifest['model_name'],
        'endpoint': 'https://api.example.com/predict',
        'status': 'active',
        'config': manifest['config'],
        'data_version': manifest['data_version'],
        'deployed_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    print(f"\n   ✅ Deployed to: {deployment['endpoint']}")
    print(f"   📊 Status: {deployment['status']}")
    
    # Save deployment record
    with open('models/deployment_record.json', 'w') as f:
        json.dump(deployment, f, indent=2)
    
    return deployment


# ==============================================================================
# Main Pipeline
# ==============================================================================

def main():
    """Execute complete MLOps pipeline."""
    print("🦆" * 35)
    print("  Complete MLOps Stack")
    print("  PyTorch + MLflow + DVC + Queuack")
    print("🦆" * 35)
    
    # Setup
    setup_infrastructure()
    
    # Create pipeline
    queue = DuckQueue(db_path="complete_mlops.db")
    dag = DAG("complete_mlops_pipeline", queue=queue)
    
    print("\n🔄 Building complete MLOps pipeline...")
    
    # Step 1: Version data
    dag.add_node(
        create_versioned_dataset,
        kwargs={'version': 'v1'},
        name="dataset"
    )
    
    # Step 2: Train multiple models in parallel
    dag.add_node(
        train_pytorch_model_config1,
        name="train_config1",
        depends_on=["dataset"],
        timeout_seconds=3600
    )
    
    dag.add_node(
        train_pytorch_model_config2,
        name="train_config2",
        depends_on=["dataset"],
        timeout_seconds=3600
    )
    
    dag.add_node(
        train_pytorch_model_config3,
        name="train_config3",
        depends_on=["dataset"],
        timeout_seconds=3600
    )
    
    # Step 3: Select and register best model
    dag.add_node(
        select_and_register_best_model,
        name="register",
        depends_on=["train_config1", "train_config2", "train_config3"]
    )
    
    # Step 4: Deploy
    dag.add_node(
        deploy_model,
        name="deploy",
        depends_on=["register"]
    )
    
    # Execute
    print("\n" + "=" * 70)
    print("▶️  EXECUTING PIPELINE")
    print("=" * 70)
    
    start = time.perf_counter()
    dag.execute()
    duration = time.perf_counter() - start
    
    print("\n" + "=" * 70)
    print("✅ PIPELINE COMPLETED")
    print("=" * 70)
    print(f"   Duration: {duration:.2f}s")
    print(f"   Queuack DB: complete_mlops.db")
    print(f"   MLflow: ./mlruns")
    print(f"   DVC Remote: ./.dvc_remote")
    
    print("\n📊 View Results:")
    print("   1. MLflow UI: mlflow ui")
    print("   2. Open: http://localhost:5000")
    print("   3. View: experiments, models, metrics")
    
    print("\n📦 Artifacts Created:")
    print("   - models/deployment_manifest.json")
    print("   - models/deployment_record.json")
    print("   - models/*.pth (PyTorch models)")
    print("   - models/*.pth.dvc (DVC metadata)")
    
    queue.close()
    
    print("\n" + "=" * 70)
    print("🎯 COMPLETE MLOPS STACK")
    print("=" * 70)
    print("""
┌─────────────────────────────────────────────────────────────────┐
│                    TECHNOLOGY STACK                             │
├─────────────────────────────────────────────────────────────────┤
│ Queuack     → Pipeline orchestration, parallel execution        │
│ PyTorch     → Deep learning framework                           │
│ MLflow      → Experiment tracking, model registry               │
│ DVC         → Data version control, reproducibility             │
└─────────────────────────────────────────────────────────────────┘

🚀 CAPABILITIES:

1. Reproducible Experiments
   ✅ Exact data version for each model
   ✅ Git-tracked code + DVC-tracked data
   ✅ MLflow tracks all experiments
   
2. Parallel Training
   ✅ 3 models trained simultaneously
   ✅ Automatic resource management
   ✅ Fault tolerance with retries
   
3. Model Management
   ✅ Automatic best model selection
   ✅ Model registry with MLflow
   ✅ Version control with DVC
   
4. Production Deployment
   ✅ Deployment manifest
   ✅ Audit trail (data → model → deployment)
   ✅ Rollback capability
   
5. Zero Infrastructure
   ✅ No Kubernetes required
   ✅ No Airflow/Kubeflow setup
   ✅ Runs on laptop or cloud VM

📈 PRODUCTION BENEFITS:

- Compliance: Full audit trail for regulatory requirements
- Debugging: Reproduce any experiment exactly
- Collaboration: Share data/models via DVC remote
- Monitoring: Track model performance over time
- CI/CD: Integrate with existing pipelines
- Cost: No infrastructure overhead

🎓 NEXT STEPS:

1. Configure cloud storage (S3/GCS/Azure)
   - dvc remote add -d myremote s3://bucket
   
2. Add model monitoring
   - Track predictions and drift
   - Trigger retraining automatically
   
3. Implement A/B testing
   - Deploy multiple models
   - Compare performance in production
   
4. Scale to distributed training
   - Use PyTorch DDP
   - Orchestrate with Queuack
   
5. Add automated testing
   - Unit tests for transforms
   - Integration tests for pipeline
   - Performance regression tests

💡 WHEN TO USE THIS STACK:

✅ Perfect for:
   - Research to production workflows
   - Small to medium teams (1-20 people)
   - Regulated industries (finance, healthcare)
   - Rapid experimentation needed
   - Limited infrastructure budget

❌ Consider alternatives when:
   - Need real-time inference (< 10ms)
   - Distributed training (100+ GPUs)
   - Multi-tenant isolation required
   - Complex workflow UI needed

🏆 COMPARISON TO ALTERNATIVES:

Traditional Stack vs Queuack Stack:

┌────────────────────────────────────────────────────────┐
│ Traditional         │  Queuack Stack                   │
├────────────────────────────────────────────────────────┤
│ Airflow             │  Queuack (orchestration)         │
│ Kubernetes          │  Not needed                      │
│ MLflow Server       │  MLflow (local)                  │
│ S3/GCS              │  DVC (any storage)               │
│ Docker              │  Optional                        │
├────────────────────────────────────────────────────────┤
│ Setup: Days/Weeks   │  Setup: Minutes                  │
│ Ops: 2-3 people     │  Ops: 0-1 person                 │
│ Cost: $5k-50k/mo    │  Cost: $0-500/mo                 │
└────────────────────────────────────────────────────────┘
    """)
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()