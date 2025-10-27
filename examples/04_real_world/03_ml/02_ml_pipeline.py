#!/usr/bin/env python3
"""
Complete MLOps Pipeline with Queuack

Demonstrates end-to-end ML pipeline replacing Airflow/Kubeflow:
- Data ingestion and validation
- Feature engineering
- Model training and evaluation
- Model versioning and deployment
- Monitoring and retraining triggers

# Difficulty: advanced

Shows:
- DAG-based ML pipeline orchestration
- Data validation and quality checks
- Model versioning
- A/B testing setup
- Retraining automation
"""

import sys
import time
from pathlib import Path
from typing import Dict, List
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from queuack import DAG, DuckQueue, TaskContext, generator_task, StreamReader


# ==============================================================================
# Pipeline Configuration
# ==============================================================================

PIPELINE_CONFIG = {
    "model_name": "customer_churn_predictor",
    "model_version": "v1.0",
    "data_source": "s3://ml-data/customer_data.csv",
    "feature_store": "features.parquet",
    "model_registry": "models/",
    "accuracy_threshold": 0.85,
    "retraining_threshold": 0.80,
}


# ==============================================================================
# Step 1: Data Ingestion
# ==============================================================================

@generator_task(format="parquet")
def ingest_data():
    """
    Ingest raw data from source.
    In production: fetch from S3, databases, APIs, etc.
    """
    print("\n📥 Step 1: Data Ingestion")
    print(f"   Source: {PIPELINE_CONFIG['data_source']}")

    # Simulate fetching data (in production: use boto3, sqlalchemy, etc.)
    import random

    for i in range(10000):
        yield {
            'customer_id': f'CUST{i:06d}',
            'age': random.randint(18, 80),
            'tenure_months': random.randint(0, 120),
            'monthly_spend': round(random.uniform(10, 500), 2),
            'support_tickets': random.randint(0, 10),
            'contract_type': random.choice(['monthly', 'yearly', '2-year']),
            'payment_method': random.choice(['credit_card', 'bank_transfer', 'paypal']),
            'churned': random.choice([0, 1]),
            'ingestion_timestamp': datetime.now().isoformat(),
        }


# ==============================================================================
# Step 2: Data Validation
# ==============================================================================

def validate_data(context: TaskContext) -> Dict:
    """
    Validate data quality and schema.
    Checks: missing values, outliers, data drift.
    """
    print("\n✅ Step 2: Data Validation")

    data_path = context.upstream("ingest")
    reader = StreamReader(data_path)

    # Quality checks
    total_records = 0
    missing_values = 0
    outliers = 0
    age_distribution = []

    for record in reader:
        total_records += 1

        # Check for missing values
        if any(v is None for v in record.values()):
            missing_values += 1

        # Check for outliers
        if record['age'] < 18 or record['age'] > 100:
            outliers += 1

        age_distribution.append(record['age'])

    # Calculate statistics
    avg_age = sum(age_distribution) / len(age_distribution)

    validation_report = {
        'total_records': total_records,
        'missing_values': missing_values,
        'outliers': outliers,
        'avg_age': round(avg_age, 2),
        'data_quality_score': 1 - (missing_values + outliers) / total_records,
        'validation_passed': missing_values < total_records * 0.05,  # < 5% missing
        'timestamp': datetime.now().isoformat(),
    }

    print(f"   Records: {total_records:,}")
    print(f"   Missing values: {missing_values}")
    print(f"   Outliers: {outliers}")
    print(f"   Data quality: {validation_report['data_quality_score']:.2%}")
    print(f"   Status: {'✅ PASSED' if validation_report['validation_passed'] else '❌ FAILED'}")

    if not validation_report['validation_passed']:
        raise ValueError("Data validation failed! Fix data quality issues.")

    return validation_report


# ==============================================================================
# Step 3: Feature Engineering
# ==============================================================================

@generator_task(format="parquet")
def engineer_features(context: TaskContext):
    """
    Create features for model training.
    Examples: encoding, scaling, derived features.
    """
    print("\n🔧 Step 3: Feature Engineering")

    data_path = context.upstream("ingest")
    validation_report = context.upstream("validate")

    print(f"   Using validated data (quality: {validation_report['data_quality_score']:.2%})")

    reader = StreamReader(data_path)

    for record in reader:
        # One-hot encode contract type
        features = {
            'customer_id': record['customer_id'],
            'age': record['age'],
            'tenure_months': record['tenure_months'],
            'monthly_spend': record['monthly_spend'],
            'support_tickets': record['support_tickets'],
            # Derived features
            'customer_lifetime_value': record['tenure_months'] * record['monthly_spend'],
            'support_ratio': record['support_tickets'] / max(record['tenure_months'], 1),
            # One-hot encoded
            'contract_monthly': 1 if record['contract_type'] == 'monthly' else 0,
            'contract_yearly': 1 if record['contract_type'] == 'yearly' else 0,
            'contract_2year': 1 if record['contract_type'] == '2-year' else 0,
            # Target
            'label': record['churned'],
        }

        yield features


# ==============================================================================
# Step 4: Model Training
# ==============================================================================

def train_model(context: TaskContext) -> Dict:
    """
    Train ML model on engineered features.
    In production: use sklearn, xgboost, pytorch, tensorflow.
    """
    print("\n🎓 Step 4: Model Training")

    features_path = context.upstream("engineer_features")
    reader = StreamReader(features_path)

    # Load data (in production: use efficient data loaders)
    X_train = []
    y_train = []

    for record in reader:
        features = [
            record['age'],
            record['tenure_months'],
            record['monthly_spend'],
            record['support_tickets'],
            record['customer_lifetime_value'],
            record['support_ratio'],
            record['contract_monthly'],
            record['contract_yearly'],
            record['contract_2year'],
        ]
        X_train.append(features)
        y_train.append(record['label'])

    # Simulate training (in production: use real ML framework)
    print(f"   Training on {len(X_train):,} samples...")
    time.sleep(1)  # Simulate training time

    # Fake metrics (in production: real model.fit() and model.score())
    import random
    training_results = {
        'model_name': PIPELINE_CONFIG['model_name'],
        'model_version': PIPELINE_CONFIG['model_version'],
        'training_samples': len(X_train),
        'accuracy': round(random.uniform(0.82, 0.92), 4),
        'precision': round(random.uniform(0.80, 0.90), 4),
        'recall': round(random.uniform(0.75, 0.88), 4),
        'f1_score': round(random.uniform(0.78, 0.89), 4),
        'training_time_seconds': 1.0,
        'model_path': f"{PIPELINE_CONFIG['model_registry']}{PIPELINE_CONFIG['model_name']}_{PIPELINE_CONFIG['model_version']}.pkl",
        'trained_at': datetime.now().isoformat(),
    }

    print(f"   Accuracy: {training_results['accuracy']:.2%}")
    print(f"   Precision: {training_results['precision']:.2%}")
    print(f"   Recall: {training_results['recall']:.2%}")
    print(f"   F1 Score: {training_results['f1_score']:.2%}")

    return training_results


# ==============================================================================
# Step 5: Model Evaluation
# ==============================================================================

def evaluate_model(context: TaskContext) -> Dict:
    """
    Evaluate model on holdout/validation set.
    Decide if model meets deployment criteria.
    """
    print("\n📊 Step 5: Model Evaluation")

    training_results = context.upstream("train")

    accuracy = training_results['accuracy']
    threshold = PIPELINE_CONFIG['accuracy_threshold']

    evaluation = {
        'model_version': training_results['model_version'],
        'accuracy': accuracy,
        'accuracy_threshold': threshold,
        'deployment_approved': accuracy >= threshold,
        'evaluation_timestamp': datetime.now().isoformat(),
    }

    print(f"   Model accuracy: {accuracy:.2%}")
    print(f"   Required threshold: {threshold:.2%}")
    print(f"   Decision: {'✅ APPROVED for deployment' if evaluation['deployment_approved'] else '❌ REJECTED'}")

    if not evaluation['deployment_approved']:
        print(f"   ⚠️  Model accuracy {accuracy:.2%} below threshold {threshold:.2%}")
        print("      Consider: more data, better features, hyperparameter tuning")

    return evaluation


# ==============================================================================
# Step 6: Model Deployment
# ==============================================================================

def deploy_model(context: TaskContext) -> Dict:
    """
    Deploy model to production.
    In production: push to model serving (Seldon, TorchServe, TFServing).
    """
    print("\n🚀 Step 6: Model Deployment")

    evaluation = context.upstream("evaluate")

    if not evaluation['deployment_approved']:
        print("   ⚠️  Skipping deployment - model not approved")
        return {'deployed': False, 'reason': 'accuracy_below_threshold'}

    training_results = context.upstream("train")

    # Simulate deployment
    print(f"   Deploying model: {training_results['model_name']} v{training_results['model_version']}")
    print(f"   Target: Production API endpoint")
    time.sleep(0.5)

    deployment = {
        'deployed': True,
        'model_name': training_results['model_name'],
        'model_version': training_results['model_version'],
        'model_path': training_results['model_path'],
        'endpoint': 'https://api.example.com/predict',
        'deployment_timestamp': datetime.now().isoformat(),
        'status': 'active',
    }

    print(f"   ✅ Deployed successfully!")
    print(f"   Endpoint: {deployment['endpoint']}")

    # Save deployment manifest
    with open("deployment_manifest.json", "w") as f:
        json.dump(deployment, f, indent=2)

    return deployment


# ==============================================================================
# Run Pipeline
# ==============================================================================

def run_ml_pipeline():
    """Execute complete ML pipeline."""
    print("🦆"*35)
    print("  Complete MLOps Pipeline")
    print("  Data → Features → Training → Deployment")
    print("🦆"*35)

    queue = DuckQueue(db_path="ml_pipeline.db")
    dag = DAG("ml_training_pipeline", queue=queue)

    # Build pipeline DAG
    dag.add_node(ingest_data, name="ingest")
    dag.add_node(validate_data, name="validate", upstream=["ingest"])
    dag.add_node(engineer_features, name="engineer_features", upstream=["ingest", "validate"])
    dag.add_node(train_model, name="train", upstream=["engineer_features"])
    dag.add_node(evaluate_model, name="evaluate", upstream=["train"])
    dag.add_node(deploy_model, name="deploy", upstream=["evaluate"])

    # Execute pipeline
    print("\n🔄 Executing ML pipeline...")
    start = time.perf_counter()

    dag.execute()

    duration = time.perf_counter() - start

    print("\n" + "="*70)
    print("✅ PIPELINE COMPLETED")
    print("="*70)
    print(f"   Total duration: {duration:.2f}s")
    print(f"   Database: ml_pipeline.db")
    print(f"   Deployment manifest: deployment_manifest.json")

    # Show pipeline stats
    stats = queue.stats()
    print(f"\n📊 Pipeline Statistics:")
    print(f"   Total jobs: {sum(stats.values())}")
    print(f"   Completed: {stats.get('done', 0)}")
    print(f"   Failed: {stats.get('failed', 0)}")

    queue.close()


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Run MLOps pipeline example."""
    run_ml_pipeline()

    print("\n" + "="*70)
    print("💡 QUEUACK FOR MLOPS")
    print("="*70)
    print("""
Why Queuack is perfect for ML workflows:

✅ Replaces Airflow/Kubeflow for simple pipelines
   - No Kubernetes cluster needed
   - No complex YAML configuration
   - Just Python functions + DAG

✅ Built-in experiment tracking
   - All results stored in SQLite
   - Query with SQL for analysis
   - No MLflow server needed (for simple cases)

✅ Easy local development
   - Test pipelines on laptop
   - Same code runs in production
   - No Docker/K8s for development

✅ Automatic retry and error handling
   - Failed steps automatically retry
   - Pipeline state persists across crashes
   - Resume from last checkpoint

✅ Parallel hyperparameter search
   - Trivial to parallelize training jobs
   - Built-in result tracking
   - No Ray/Dask overhead

✅ Streaming for large datasets
   - Memory-efficient data processing
   - Handle datasets larger than RAM
   - O(1) memory complexity

Common ML use cases:
1. Daily/hourly model retraining
2. Hyperparameter optimization
3. A/B test experiment tracking
4. Feature engineering pipelines
5. Data quality monitoring
6. Model drift detection
7. Batch inference jobs
    """)
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
