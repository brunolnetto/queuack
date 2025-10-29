#!/usr/bin/env python3
"""
Scikit-learn Binary Classification Pipeline

Demonstrates a complete scikit-learn ML pipeline with Queuack:
- Data loading and preprocessing
- Feature engineering
- Model training with cross-validation
- Model evaluation and selection
- Prediction on new data

This is a lighter alternative to PyTorch for traditional ML tasks.

# Difficulty: intermediate

Shows:
- Scikit-learn integration
- Cross-validation in DAG
- Feature engineering pipeline
- Model comparison
- Production predictions
"""

import sys
import time
import pickle
from pathlib import Path
from typing import Dict, List, Tuple
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from queuack import DAG, TaskContext, DuckQueue, generator_task, StreamReader


# ==============================================================================
# Step 1: Generate Sample Dataset (or load from file/database)
# ==============================================================================

@generator_task(format="jsonl")
def load_data():
    """
    Load or generate training data.
    
    In production: Replace with actual data loading from:
    - CSV files (pandas.read_csv)
    - Databases (sqlalchemy)
    - APIs (requests)
    - Cloud storage (boto3 for S3)
    """
    print("\n📥 Step 1: Loading Data")
    
    import random
    random.seed(42)
    
    # Generate synthetic customer churn data
    for i in range(10000):
        # Features
        age = random.randint(18, 80)
        tenure = random.randint(0, 120)
        monthly_charges = random.uniform(20, 200)
        total_charges = tenure * monthly_charges + random.uniform(-500, 500)
        
        # Target: churn probability based on features
        churn_score = (
            -0.01 * age +
            -0.02 * tenure +
            0.005 * monthly_charges +
            random.uniform(-0.5, 0.5)
        )
        churn = 1 if churn_score > 0 else 0
        
        yield {
            'customer_id': f'CUST{i:06d}',
            'age': age,
            'tenure_months': tenure,
            'monthly_charges': monthly_charges,
            'total_charges': total_charges,
            'contract_type': random.choice(['Month-to-month', 'One year', 'Two year']),
            'payment_method': random.choice(['Electronic check', 'Mailed check', 'Bank transfer', 'Credit card']),
            'churn': churn
        }


# ==============================================================================
# Step 2: Feature Engineering
# ==============================================================================

@generator_task(format="jsonl")
def engineer_features(context: TaskContext):
    """
    Create features for model training.
    
    Feature engineering techniques:
    - Derived features (ratios, aggregations)
    - One-hot encoding for categorical variables
    - Feature scaling (handled in training step)
    """
    print("\n🔧 Step 2: Feature Engineering")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    for record in reader:
        # Derived features
        avg_monthly_charges = record['total_charges'] / max(record['tenure_months'], 1)
        charges_to_age_ratio = record['monthly_charges'] / record['age']
        
        # One-hot encode contract type
        contract_month = 1 if record['contract_type'] == 'Month-to-month' else 0
        contract_one_year = 1 if record['contract_type'] == 'One year' else 0
        contract_two_year = 1 if record['contract_type'] == 'Two year' else 0
        
        # One-hot encode payment method
        payment_check = 1 if 'check' in record['payment_method'].lower() else 0
        payment_bank = 1 if 'bank' in record['payment_method'].lower() else 0
        payment_credit = 1 if 'credit' in record['payment_method'].lower() else 0
        
        yield {
            'customer_id': record['customer_id'],
            # Original features
            'age': record['age'],
            'tenure_months': record['tenure_months'],
            'monthly_charges': record['monthly_charges'],
            'total_charges': record['total_charges'],
            # Derived features
            'avg_monthly_charges': avg_monthly_charges,
            'charges_to_age_ratio': charges_to_age_ratio,
            # Encoded features
            'contract_month': contract_month,
            'contract_one_year': contract_one_year,
            'contract_two_year': contract_two_year,
            'payment_check': payment_check,
            'payment_bank': payment_bank,
            'payment_credit': payment_credit,
            # Target
            'churn': record['churn']
        }


# ==============================================================================
# Step 3: Train Models (Multiple Algorithms in Parallel)
# ==============================================================================

def train_logistic_regression(context: TaskContext) -> Dict:
    """Train logistic regression model."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n🎯 Training: Logistic Regression")
    
    features_path = context.upstream("features")
    reader = StreamReader(features_path)
    
    # Load data
    X = []
    y = []
    feature_names = ['age', 'tenure_months', 'monthly_charges', 'total_charges',
                     'avg_monthly_charges', 'charges_to_age_ratio',
                     'contract_month', 'contract_one_year', 'contract_two_year',
                     'payment_check', 'payment_bank', 'payment_credit']
    
    for record in reader:
        features = [record[name] for name in feature_names]
        X.append(features)
        y.append(record['churn'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Train model with cross-validation
    model = LogisticRegression(max_iter=1000, random_state=42)
    cv_scores = cross_val_score(model, X_scaled, y, cv=5, scoring='accuracy')
    
    # Final training on full dataset
    model.fit(X_scaled, y)
    
    # Save model and scaler
    model_path = "models/logistic_regression.pkl"
    Path("models").mkdir(exist_ok=True)
    
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler, 'feature_names': feature_names}, f)
    
    result = {
        'model_type': 'LogisticRegression',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'cv_scores': cv_scores.tolist(),
        'n_samples': len(X),
        'n_features': len(feature_names)
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    
    return result


def train_random_forest(context: TaskContext) -> Dict:
    """Train random forest model."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n🌳 Training: Random Forest")
    
    features_path = context.upstream("features")
    reader = StreamReader(features_path)
    
    # Load data (same process as logistic regression)
    X = []
    y = []
    feature_names = ['age', 'tenure_months', 'monthly_charges', 'total_charges',
                     'avg_monthly_charges', 'charges_to_age_ratio',
                     'contract_month', 'contract_one_year', 'contract_two_year',
                     'payment_check', 'payment_bank', 'payment_credit']
    
    for record in reader:
        features = [record[name] for name in feature_names]
        X.append(features)
        y.append(record['churn'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Train random forest with cross-validation
    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    
    # Final training
    model.fit(X, y)
    
    # Save model
    model_path = "models/random_forest.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'feature_names': feature_names}, f)
    
    result = {
        'model_type': 'RandomForest',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'cv_scores': cv_scores.tolist(),
        'n_samples': len(X),
        'n_features': len(feature_names),
        'feature_importance': model.feature_importances_.tolist()
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    
    return result


def train_gradient_boosting(context: TaskContext) -> Dict:
    """Train gradient boosting model."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n⚡ Training: Gradient Boosting")
    
    features_path = context.upstream("features")
    reader = StreamReader(features_path)
    
    # Load data
    X = []
    y = []
    feature_names = ['age', 'tenure_months', 'monthly_charges', 'total_charges',
                     'avg_monthly_charges', 'charges_to_age_ratio',
                     'contract_month', 'contract_one_year', 'contract_two_year',
                     'payment_check', 'payment_bank', 'payment_credit']
    
    for record in reader:
        features = [record[name] for name in feature_names]
        X.append(features)
        y.append(record['churn'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Train gradient boosting with cross-validation
    model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    
    # Final training
    model.fit(X, y)
    
    # Save model
    model_path = "models/gradient_boosting.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'feature_names': feature_names}, f)
    
    result = {
        'model_type': 'GradientBoosting',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'cv_scores': cv_scores.tolist(),
        'n_samples': len(X),
        'n_features': len(feature_names),
        'feature_importance': model.feature_importances_.tolist()
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    
    return result


# ==============================================================================
# Step 4: Select Best Model
# ==============================================================================

def select_best_model(context: TaskContext) -> Dict:
    """
    Compare all trained models and select the best one.
    
    Uses context.upstream_all() to get all model results.
    """
    print("\n🏆 Step 4: Model Selection")
    
    # Get all model results
    all_results = context.upstream_all()
    
    print(f"\n   Comparing {len(all_results)} models:")
    for name, result in all_results.items():
        print(f"   - {result['model_type']}: {result['cv_accuracy_mean']:.4f}")
    
    # Select best by CV accuracy
    best_model_name = max(all_results.keys(), 
                          key=lambda k: all_results[k]['cv_accuracy_mean'])
    best_result = all_results[best_model_name]
    
    print(f"\n   ✅ Best Model: {best_result['model_type']}")
    print(f"      Accuracy: {best_result['cv_accuracy_mean']:.4f} (+/- {best_result['cv_accuracy_std']:.4f})")
    
    # Save selection metadata
    selection = {
        'best_model': best_result['model_type'],
        'best_model_path': best_result['model_path'],
        'best_accuracy': best_result['cv_accuracy_mean'],
        'all_models': {name: res['cv_accuracy_mean'] for name, res in all_results.items()}
    }
    
    with open("models/best_model.json", 'w') as f:
        json.dump(selection, f, indent=2)
    
    return selection


# ==============================================================================
# Step 5: Make Predictions on New Data
# ==============================================================================

def predict_churn(context: TaskContext) -> Dict:
    """
    Make predictions using the best model.
    
    In production: This would be called with new customer data.
    """
    print("\n🔮 Step 5: Making Predictions")
    
    selection = context.upstream("select_best")
    
    # Load best model
    with open(selection['best_model_path'], 'rb') as f:
        model_data = pickle.load(f)
    
    model = model_data['model']
    feature_names = model_data['feature_names']
    
    # Example new customers to predict
    new_customers = [
        {'age': 45, 'tenure_months': 24, 'monthly_charges': 75.5, 'total_charges': 1850.0,
         'avg_monthly_charges': 77.08, 'charges_to_age_ratio': 1.68,
         'contract_month': 0, 'contract_one_year': 1, 'contract_two_year': 0,
         'payment_check': 0, 'payment_bank': 1, 'payment_credit': 0},
        {'age': 30, 'tenure_months': 3, 'monthly_charges': 120.0, 'total_charges': 360.0,
         'avg_monthly_charges': 120.0, 'charges_to_age_ratio': 4.0,
         'contract_month': 1, 'contract_one_year': 0, 'contract_two_year': 0,
         'payment_check': 1, 'payment_bank': 0, 'payment_credit': 0}
    ]
    
    # Prepare features
    import numpy as np
    X_new = np.array([[c[name] for name in feature_names] for c in new_customers])
    
    # Handle scaling if needed (logistic regression)
    if 'scaler' in model_data:
        X_new = model_data['scaler'].transform(X_new)
    
    # Predict
    predictions = model.predict(X_new)
    probabilities = model.predict_proba(X_new)
    
    results = {
        'model_used': selection['best_model'],
        'predictions': [
            {
                'customer': i + 1,
                'churn_prediction': int(pred),
                'churn_probability': float(prob[1])
            }
            for i, (pred, prob) in enumerate(zip(predictions, probabilities))
        ]
    }
    
    print(f"\n   Using model: {results['model_used']}")
    for pred in results['predictions']:
        print(f"   Customer {pred['customer']}: {'WILL CHURN' if pred['churn_prediction'] else 'WILL STAY'} "
              f"(probability: {pred['churn_probability']:.2%})")
    
    return results


# ==============================================================================
# Run Pipeline
# ==============================================================================

def main():
    """Execute the complete scikit-learn ML pipeline."""
    print("🦆" * 35)
    print("  Scikit-learn Classification Pipeline")
    print("  Queuack + Scikit-learn for Traditional ML")
    print("🦆" * 35)
    
    queue = DuckQueue(db_path="sklearn_pipeline.db")
    dag = DAG("sklearn_classification", queue=queue)
    
    # Build pipeline
    dag.add_node(load_data, name="load")
    dag.add_node(engineer_features, name="features", depends_on=["load"])
    
    # Train multiple models in parallel
    dag.add_node(train_logistic_regression, name="train_logistic", depends_on=["features"])
    dag.add_node(train_random_forest, name="train_rf", depends_on=["features"])
    dag.add_node(train_gradient_boosting, name="train_gb", depends_on=["features"])
    
    # Select best and predict
    dag.add_node(select_best_model, name="select_best", 
                 depends_on=["train_logistic", "train_rf", "train_gb"])
    dag.add_node(predict_churn, name="predict", depends_on=["select_best"])
    
    # Execute
    print("\n🔄 Executing pipeline...")
    start = time.perf_counter()
    
    dag.execute()
    
    duration = time.perf_counter() - start
    
    print("\n" + "=" * 70)
    print("✅ PIPELINE COMPLETED")
    print("=" * 70)
    print(f"   Duration: {duration:.2f}s")
    print(f"   Database: sklearn_pipeline.db")
    print(f"   Models: models/")
    print(f"   Best model: models/best_model.json")
    
    queue.close()
    
    print("\n💡 Scikit-learn + Queuack Benefits:")
    print("""
   ✅ Parallel model training (3 models trained simultaneously)
   ✅ Cross-validation for robust evaluation
   ✅ Feature engineering pipeline
   ✅ Automatic model selection
   ✅ Production-ready predictions
   ✅ All results tracked in DuckDB
   ✅ Crash recovery (resume from last checkpoint)
   ✅ Memory-efficient streaming for large datasets
   
   Common use cases:
   - Customer churn prediction
   - Fraud detection
   - Credit scoring
   - Recommendation systems
   - Demand forecasting
   - A/B test analysis
    """)


if __name__ == "__main__":
    main()