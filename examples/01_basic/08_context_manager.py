"""08_context_manager.py - Using DuckQueue with context manager

# Difficulty: beginner
"""
from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

def greet(name: str):
    print(f"Hello, {name}!")
    return f"Greeted {name}"

db_path = create_temp_path("context")

# Context manager automatically starts/stops workers
with DuckQueue(db_path, workers_num=2, worker_concurrency=2) as queue:
    # Enqueue jobs
    for name in ["Alice", "Bob", "Charlie"]:
        queue.enqueue(greet, args=(name,))
    
    print(f"Enqueued 3 jobs, workers processing...")
    print(f"Stats: {queue.stats()}")
    
    # Workers run automatically in background
    import time
    time.sleep(1)
    
    print(f"Final stats: {queue.stats()}")

# Workers automatically stopped when context exits
print("Context exited, workers stopped")