#!/usr/bin/env python3
"""
Scikit-learn Ensemble Learning Pipeline

Demonstrates training multiple sklearn models in parallel and combining them
into an ensemble for improved predictions.

Ensemble techniques:
- Voting Classifier: Combine multiple models via voting
- Stacking: Train meta-model on base model predictions
- Bagging/Boosting: Already parallel in sklearn

# Difficulty: intermediate

Requirements:
    pip install scikit-learn pandas numpy

Shows:
- Parallel training of diverse algorithms
- Ensemble model creation
- Meta-model training
- Model diversity analysis
- Production ensemble deployment
"""

import sys
import time
import pickle
from pathlib import Path
from typing import Dict, List
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from queuack import DAG, TaskContext, DuckQueue, generator_task, StreamReader


# ==============================================================================
# Step 1: Generate Dataset
# ==============================================================================

@generator_task(format="jsonl")
def load_data():
    """Generate synthetic classification dataset."""
    print("\n📊 Step 1: Loading Data")
    
    from sklearn.datasets import make_classification
    
    # Generate synthetic dataset
    X, y = make_classification(
        n_samples=10000,
        n_features=20,
        n_informative=15,
        n_redundant=5,
        n_classes=2,
        random_state=42
    )
    
    # Yield as records
    for i in range(len(X)):
        yield {
            'features': X[i].tolist(),
            'target': int(y[i])
        }


# ==============================================================================
# Step 2: Train Individual Models (Base Learners)
# ==============================================================================

def train_logistic_regression(context: TaskContext) -> Dict:
    """Train logistic regression model."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n🎯 Training: Logistic Regression")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Train with cross-validation
    model = LogisticRegression(max_iter=1000, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    
    # Final training
    model.fit(X, y)
    
    # Save model
    model_path = "models/ensemble_logistic.pkl"
    Path("models").mkdir(exist_ok=True)
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    
    result = {
        'model_type': 'LogisticRegression',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std())
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    return result


def train_random_forest(context: TaskContext) -> Dict:
    """Train random forest model."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n🌳 Training: Random Forest")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    
    model.fit(X, y)
    
    model_path = "models/ensemble_rf.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    
    result = {
        'model_type': 'RandomForest',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std())
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    return result


def train_gradient_boosting(context: TaskContext) -> Dict:
    """Train gradient boosting model."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n⚡ Training: Gradient Boosting")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    model = GradientBoostingClassifier(n_estimators=100, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    
    model.fit(X, y)
    
    model_path = "models/ensemble_gb.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    
    result = {
        'model_type': 'GradientBoosting',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std())
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    return result


def train_svm(context: TaskContext) -> Dict:
    """Train SVM model."""
    from sklearn.svm import SVC
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    
    print("\n🎲 Training: SVM")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    # SVM needs scaled features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    model = SVC(probability=True, random_state=42)
    cv_scores = cross_val_score(model, X_scaled, y, cv=5, scoring='accuracy')
    
    model.fit(X_scaled, y)
    
    model_path = "models/ensemble_svm.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler}, f)
    
    result = {
        'model_type': 'SVM',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std())
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    return result


def train_knn(context: TaskContext) -> Dict:
    """Train K-Nearest Neighbors model."""
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    
    print("\n👥 Training: K-Nearest Neighbors")
    
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    # KNN needs scaled features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    model = KNeighborsClassifier(n_neighbors=5)
    cv_scores = cross_val_score(model, X_scaled, y, cv=5, scoring='accuracy')
    
    model.fit(X_scaled, y)
    
    model_path = "models/ensemble_knn.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler}, f)
    
    result = {
        'model_type': 'KNN',
        'model_path': model_path,
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std())
    }
    
    print(f"   CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    return result


# ==============================================================================
# Step 3: Create Ensemble Models
# ==============================================================================

def create_voting_ensemble(context: TaskContext) -> Dict:
    """
    Create voting ensemble from base models.
    
    Uses context.upstream_all() to get all trained models.
    """
    from sklearn.ensemble import VotingClassifier
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n🗳️  Step 3a: Creating Voting Ensemble")
    
    # Get all base model results
    all_results = context.upstream_all()
    
    print(f"   Using {len(all_results)} base models:")
    for name, result in all_results.items():
        print(f"   - {result['model_type']}: {result['cv_accuracy_mean']:.4f}")
    
    # Load data
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Load base models
    estimators = []
    for name, result in all_results.items():
        with open(result['model_path'], 'rb') as f:
            model_data = pickle.load(f)
            
            # Handle models that need scaling
            if isinstance(model_data, dict):
                model = model_data['model']
            else:
                model = model_data
            
            estimators.append((result['model_type'], model))
    
    # Create voting ensemble (hard voting)
    voting_clf = VotingClassifier(
        estimators=estimators,
        voting='hard'
    )
    
    # Evaluate with cross-validation
    cv_scores = cross_val_score(voting_clf, X, y, cv=5, scoring='accuracy')
    
    # Train final model
    voting_clf.fit(X, y)
    
    # Save ensemble
    ensemble_path = "models/voting_ensemble.pkl"
    with open(ensemble_path, 'wb') as f:
        pickle.dump(voting_clf, f)
    
    result = {
        'ensemble_type': 'VotingClassifier',
        'ensemble_path': ensemble_path,
        'n_base_models': len(estimators),
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'base_models': [name for name, _ in estimators]
    }
    
    print(f"\n   ✅ Voting Ensemble Created")
    print(f"      Base models: {len(estimators)}")
    print(f"      CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    
    # Compare to base models
    best_base = max(all_results.values(), key=lambda x: x['cv_accuracy_mean'])
    improvement = result['cv_accuracy_mean'] - best_base['cv_accuracy_mean']
    
    print(f"      Best base model: {best_base['cv_accuracy_mean']:.4f}")
    print(f"      Improvement: {improvement:+.4f} ({improvement*100:+.2f}%)")
    
    return result


def create_stacking_ensemble(context: TaskContext) -> Dict:
    """
    Create stacking ensemble with meta-learner.
    
    Trains a meta-model on predictions from base models.
    """
    from sklearn.ensemble import StackingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    import numpy as np
    
    print("\n📚 Step 3b: Creating Stacking Ensemble")
    
    # Get base model results (excluding voting ensemble)
    all_results = context.upstream_all()
    base_results = {k: v for k, v in all_results.items() 
                    if k.startswith('train_')}  # Only base models
    
    print(f"   Using {len(base_results)} base models for stacking:")
    for name, result in base_results.items():
        print(f"   - {result['model_type']}: {result['cv_accuracy_mean']:.4f}")
    
    # Load data
    data_path = context.upstream("load")
    reader = StreamReader(data_path)
    
    X = []
    y = []
    for record in reader:
        X.append(record['features'])
        y.append(record['target'])
    
    X = np.array(X)
    y = np.array(y)
    
    # Load base models
    estimators = []
    for name, result in base_results.items():
        with open(result['model_path'], 'rb') as f:
            model_data = pickle.load(f)
            
            if isinstance(model_data, dict):
                model = model_data['model']
            else:
                model = model_data
            
            estimators.append((result['model_type'], model))
    
    # Create stacking ensemble with logistic regression as meta-learner
    stacking_clf = StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(max_iter=1000),
        cv=5
    )
    
    # Evaluate
    cv_scores = cross_val_score(stacking_clf, X, y, cv=5, scoring='accuracy')
    
    # Train
    stacking_clf.fit(X, y)
    
    # Save
    ensemble_path = "models/stacking_ensemble.pkl"
    with open(ensemble_path, 'wb') as f:
        pickle.dump(stacking_clf, f)
    
    result = {
        'ensemble_type': 'StackingClassifier',
        'ensemble_path': ensemble_path,
        'n_base_models': len(estimators),
        'meta_learner': 'LogisticRegression',
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'base_models': [name for name, _ in estimators]
    }
    
    print(f"\n   ✅ Stacking Ensemble Created")
    print(f"      Base models: {len(estimators)}")
    print(f"      Meta-learner: LogisticRegression")
    print(f"      CV Accuracy: {result['cv_accuracy_mean']:.4f} (+/- {result['cv_accuracy_std']:.4f})")
    
    return result


# ==============================================================================
# Step 4: Compare All Models
# ==============================================================================

def compare_all_models(context: TaskContext) -> Dict:
    """
    Compare base models and ensembles.
    
    Final analysis of model performance.
    """
    print("\n📊 Step 4: Comparing All Models")
    
    # Get all results
    all_results = context.upstream_all()
    
    # Separate base models and ensembles
    base_models = {}
    ensembles = {}
    
    for name, result in all_results.items():
        if 'ensemble_type' in result:
            ensembles[name] = result
        elif 'model_type' in result:
            base_models[name] = result
    
    print(f"\n   📋 Base Models ({len(base_models)}):")
    for name, result in sorted(base_models.items(), 
                               key=lambda x: x[1]['cv_accuracy_mean'], 
                               reverse=True):
        print(f"      {result['model_type']}: {result['cv_accuracy_mean']:.4f}")
    
    print(f"\n   🎯 Ensemble Models ({len(ensembles)}):")
    for name, result in sorted(ensembles.items(),
                               key=lambda x: x[1]['cv_accuracy_mean'],
                               reverse=True):
        print(f"      {result['ensemble_type']}: {result['cv_accuracy_mean']:.4f}")
    
    # Find best overall
    all_models = {**base_models, **ensembles}
    best_name = max(all_models.keys(), 
                    key=lambda k: all_models[k]['cv_accuracy_mean'])
    best_result = all_models[best_name]
    
    print(f"\n   🏆 Best Model: {best_result.get('ensemble_type') or best_result.get('model_type')}")
    print(f"      Accuracy: {best_result['cv_accuracy_mean']:.4f}")
    
    # Save comparison
    comparison = {
        'best_model': best_result.get('ensemble_type') or best_result.get('model_type'),
        'best_accuracy': best_result['cv_accuracy_mean'],
        'base_models': {k: v['cv_accuracy_mean'] for k, v in base_models.items()},
        'ensembles': {k: v['cv_accuracy_mean'] for k, v in ensembles.items()}
    }
    
    with open('models/ensemble_comparison.json', 'w') as f:
        json.dump(comparison, f, indent=2)
    
    return comparison


# ==============================================================================
# Main Pipeline
# ==============================================================================

def main():
    """Execute ensemble learning pipeline."""
    print("🦆" * 35)
    print("  Scikit-learn Ensemble Learning")
    print("  Parallel Training + Model Combination")
    print("🦆" * 35)
    
    queue = DuckQueue(db_path="ensemble_pipeline.db")
    dag = DAG("sklearn_ensemble", queue=queue)
    
    # Step 1: Load data
    dag.add_node(load_data, name="load")
    
    # Step 2: Train base models in parallel
    dag.add_node(train_logistic_regression, name="train_logistic", depends_on=["load"])
    dag.add_node(train_random_forest, name="train_rf", depends_on=["load"])
    dag.add_node(train_gradient_boosting, name="train_gb", depends_on=["load"])
    dag.add_node(train_svm, name="train_svm", depends_on=["load"])
    dag.add_node(train_knn, name="train_knn", depends_on=["load"])
    
    # Step 3: Create ensembles
    base_models = ["train_logistic", "train_rf", "train_gb", "train_svm", "train_knn"]
    
    dag.add_node(
        create_voting_ensemble,
        name="voting",
        depends_on=["load"] + base_models
    )
    
    dag.add_node(
        create_stacking_ensemble,
        name="stacking",
        depends_on=["load"] + base_models
    )
    
    # Step 4: Compare
    dag.add_node(
        compare_all_models,
        name="compare",
        depends_on=base_models + ["voting", "stacking"]
    )
    
    # Execute
    print("\n🔄 Executing ensemble pipeline...")
    start = time.perf_counter()
    
    dag.execute()
    
    duration = time.perf_counter() - start
    
    print("\n" + "=" * 70)
    print("✅ PIPELINE COMPLETED")
    print("=" * 70)
    print(f"   Duration: {duration:.2f}s")
    print(f"   Models trained: 5 base + 2 ensembles")
    print(f"   Results: models/ensemble_comparison.json")
    
    queue.close()
    
    print("\n💡 Ensemble Learning Benefits:")
    print("""
   ✅ Improved accuracy through model diversity
   ✅ Reduced overfitting via averaging
   ✅ Robust predictions across data distributions
   ✅ Parallel training of base models
   ✅ Multiple ensemble strategies (voting, stacking)
   
   When to use ensembles:
   - Need highest possible accuracy
   - Have computational resources
   - Can tolerate slower predictions
   - Want robust production models
   
   Queuack advantages:
   - Train all base models in parallel (5x speedup)
   - Automatic result aggregation
   - Easy ensemble creation
   - Crash recovery if training fails
    """)


if __name__ == "__main__":
    main()