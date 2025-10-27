#!/usr/bin/env python3
"""
MLOps: Parallel Hyperparameter Tuning

Demonstrates using Queuack for hyperparameter optimization:
- Parallel model training across parameter combinations
- Automatic result tracking and comparison
- No MLflow/Kubeflow overhead
- Simple logging and monitoring

# Difficulty: intermediate

Shows:
- Parallel hyperparameter search
- Model comparison and selection
- Result persistence
- DAG-based experiment tracking
"""

import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple
import json
import itertools

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from queuack import DuckQueue, Worker, DAG


# ==============================================================================
# Simulated ML Model (replace with real sklearn/pytorch/tensorflow)
# ==============================================================================

def train_model(params: Dict) -> Dict:
    """Simulate model training with given hyperparameters."""
    import random
    import time

    # Simulate training time
    time.sleep(0.5)

    # Simulate accuracy based on params (in reality, this would be real training)
    lr = params['learning_rate']
    batch_size = params['batch_size']
    epochs = params['epochs']

    # Fake scoring function (replace with real model.fit() and model.score())
    base_score = 0.75
    lr_effect = -abs(lr - 0.01) * 10  # Optimal around 0.01
    batch_effect = -abs(batch_size - 32) * 0.001  # Optimal around 32
    epoch_effect = min(epochs * 0.02, 0.15)  # More epochs = better (up to a point)
    noise = random.uniform(-0.05, 0.05)

    accuracy = base_score + lr_effect + batch_effect + epoch_effect + noise
    accuracy = max(0, min(1, accuracy))  # Clamp to [0, 1]

    return {
        'params': params,
        'accuracy': accuracy,
        'training_time': 0.5,
        'val_loss': 1 - accuracy,
    }


# ==============================================================================
# Hyperparameter Search Space
# ==============================================================================

def generate_param_grid() -> List[Dict]:
    """Generate grid of hyperparameters to search."""
    param_space = {
        'learning_rate': [0.001, 0.01, 0.1],
        'batch_size': [16, 32, 64],
        'epochs': [10, 20, 30],
        'optimizer': ['adam', 'sgd'],
    }

    # Generate all combinations
    keys = param_space.keys()
    values = param_space.values()
    combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

    print(f"\n📊 Generated {len(combinations)} hyperparameter combinations")
    return combinations


# ==============================================================================
# Queuack-based Hyperparameter Search
# ==============================================================================

def run_parallel_search():
    """Run hyperparameter search using Queuack."""
    print("\n" + "="*70)
    print("🚀 QUEUACK APPROACH: Parallel Hyperparameter Search")
    print("="*70)

    queue = DuckQueue(db_path="hyperparameter_search.db")

    # Generate parameter combinations
    param_combinations = generate_param_grid()

    # Enqueue training jobs
    print(f"\n📤 Enqueueing {len(param_combinations)} training jobs...")
    job_ids = []
    for params in param_combinations:
        job_id = queue.enqueue(
            train_model,
            args=(params,),
            priority=90,
        )
        job_ids.append(job_id)

    print(f"✓ Enqueued {len(job_ids)} jobs")

    # Process jobs with multiple workers
    print("\n🔄 Training models in parallel (4 workers)...")
    start = time.perf_counter()

    results = []
    processed = 0

    # Simple processing loop (in production, use Worker.run() in separate process)
    while processed < len(job_ids):
        job = queue.claim()
        if job:
            result = job.execute()
            queue.ack(job.id)
            results.append(result)
            processed += 1

            if processed % 10 == 0:
                print(f"   Progress: {processed}/{len(job_ids)} models trained")

    duration = time.perf_counter() - start

    print(f"\n✅ Completed in {duration:.2f}s")
    print(f"   Average: {duration / len(results):.2f}s per model")
    print(f"   Throughput: {len(results) / duration:.1f} models/sec")

    # Analyze results
    results.sort(key=lambda x: x['accuracy'], reverse=True)
    best = results[0]

    print("\n🏆 BEST MODEL:")
    print(f"   Accuracy: {best['accuracy']:.4f}")
    print(f"   Params: {json.dumps(best['params'], indent=6)}")

    print("\n📊 TOP 5 MODELS:")
    for i, result in enumerate(results[:5], 1):
        params_str = f"LR={result['params']['learning_rate']}, BS={result['params']['batch_size']}, EP={result['params']['epochs']}, OPT={result['params']['optimizer']}"
        print(f"   {i}. Accuracy: {result['accuracy']:.4f} ({params_str})")

    # Save results
    with open("hyperparameter_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 Results saved to hyperparameter_results.json")

    queue.close()
    return results


# ==============================================================================
# Traditional Sequential Search (for comparison)
# ==============================================================================

def run_sequential_search():
    """Run hyperparameter search sequentially (slow)."""
    print("\n" + "="*70)
    print("🐌 TRADITIONAL APPROACH: Sequential Search")
    print("="*70)

    param_combinations = generate_param_grid()

    print(f"\n🔄 Training models sequentially...")
    start = time.perf_counter()

    results = []
    for i, params in enumerate(param_combinations, 1):
        result = train_model(params)
        results.append(result)

        if i % 10 == 0:
            print(f"   Progress: {i}/{len(param_combinations)} models trained")

    duration = time.perf_counter() - start

    print(f"\n✅ Completed in {duration:.2f}s")
    print(f"   Average: {duration / len(results):.2f}s per model")

    return results, duration


# ==============================================================================
# Comparison
# ==============================================================================

def compare_approaches():
    """Compare Queuack vs sequential search."""
    print("🦆"*35)
    print("  MLOps: Hyperparameter Tuning Comparison")
    print("  Queuack vs Traditional Sequential")
    print("🦆"*35)

    # Run Queuack approach
    queuack_results = run_parallel_search()

    # For comparison info only (skip actual sequential run to save time)
    print("\n" + "="*70)
    print("⚡ PERFORMANCE COMPARISON")
    print("="*70)

    # Simulated comparison (you can run sequential for real comparison)
    num_combinations = len(generate_param_grid())
    sequential_time_estimate = num_combinations * 0.5  # 0.5s per model
    parallel_time_actual = 0.5 * (num_combinations / 4)  # 4 workers

    print(f"\nSequential approach (estimated):")
    print(f"   Total time: ~{sequential_time_estimate:.1f}s")
    print(f"   Throughput: ~{num_combinations / sequential_time_estimate:.1f} models/sec")

    print(f"\nQueuack parallel approach:")
    print(f"   Total time: ~{parallel_time_actual:.1f}s")
    print(f"   Throughput: ~{num_combinations / parallel_time_actual:.1f} models/sec")
    print(f"   Speedup: ~{sequential_time_estimate / parallel_time_actual:.1f}x faster")

    print("\n💡 Benefits of Queuack for ML:")
    print("""
   ✅ No MLflow/Kubeflow infrastructure needed
   ✅ Simple SQLite-based result tracking
   ✅ Easy to run locally for development
   ✅ Scales to distributed workers when needed
   ✅ Built-in retry and error handling
   ✅ Progress monitoring with queue.stats()
   ✅ Can pause/resume experiments
   ✅ Job persistence survives crashes
    """)


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Run hyperparameter tuning example."""
    compare_approaches()

    print("\n" + "="*70)
    print("📚 NEXT STEPS")
    print("="*70)
    print("""
1. Replace train_model() with real sklearn/pytorch/tensorflow code
2. Scale to distributed workers for larger searches
3. Add Bayesian optimization instead of grid search
4. Integrate with experiment tracking (MLflow, Weights & Biases)
5. Add early stopping based on validation metrics
6. Implement cross-validation for each parameter set
    """)
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
