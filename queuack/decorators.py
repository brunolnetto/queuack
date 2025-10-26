"""
Decorators for common task patterns in Queuack.

This module provides convenience decorators that reduce boilerplate and
enforce best practices for specific task types.
"""

from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, Union
import time

from .data_models import TaskContext


def streaming_task(func: Callable) -> Callable:
    """Decorator for file-based streaming tasks.
    
    Automatically handles common patterns for tasks that:
    - Read from file paths (not in-memory data)
    - Write to file paths (not in-memory data)
    - Should close TaskContext immediately after reading dependencies
    
    Benefits:
    - Automatically closes TaskContext after dependency resolution
    - Validates return value is a file path
    - Logs execution time
    - Reduces boilerplate in streaming pipelines
    
    The decorated function should:
    1. Accept TaskContext as first argument (or via context= kwarg)
    2. Use context.upstream() to get input file paths
    3. Return output file path(s)
    
    Args:
        func: Task function to decorate
    
    Returns:
        Wrapped function with automatic context management
    
    Example - Basic usage:
        @streaming_task
        def transform(context: TaskContext):
            input_path = context.upstream("extract")
            # Context is auto-closed here
            
            # Process file
            output_path = "data/output.jsonl"
            with open(input_path) as infile:
                with open(output_path, "w") as outfile:
                    for line in infile:
                        # Transform line by line
                        outfile.write(process(line))
            
            return output_path  # Must return file path
    
    Example - With external framework:
        @streaming_task
        def spark_transform(context: TaskContext):
            input_path = context.upstream("extract")
            # Context closed, safe to use Spark now
            
            spark = SparkSession.builder.getOrCreate()
            df = spark.read.json(input_path)
            df_transformed = df.filter(...)
            
            output_path = "data/output.parquet"
            df_transformed.write.parquet(output_path)
            return output_path
    
    Example - Multiple inputs:
        @streaming_task
        def merge(context: TaskContext):
            paths = context.upstream_all()
            # paths = {"extract_a": "data/a.csv", "extract_b": "data/b.csv"}
            # Context closed
            
            output_path = "data/merged.csv"
            merge_files(paths.values(), output_path)
            return output_path
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Find TaskContext in args or kwargs
        context = None
        new_args = []
        
        for arg in args:
            if isinstance(arg, TaskContext):
                context = arg
            else:
                new_args.append(arg)
        
        if context is None:
            context = kwargs.pop('context', None)
        
        if context is None:
            # No context provided - call function as-is
            return func(*args, **kwargs)
        
        # Execute with timing and auto-cleanup
        start = time.perf_counter()
        func_name = func.__name__
        
        try:
            # Call function with context
            result = func(context, *new_args, **kwargs)
        finally:
            # Force context cleanup even on exceptions
            if context and hasattr(context, '_queue') and context._queue is not None:
                try:
                    context.close()
                except Exception:
                    pass  # Ignore cleanup errors
        
        # Validate result is a path-like object
        if result is not None:
            is_path = isinstance(result, (str, Path))
            is_path_list = isinstance(result, (list, tuple)) and all(
                isinstance(x, (str, Path)) for x in result
            )
            
            if not is_path and not is_path_list:
                import warnings
                warnings.warn(
                    f"{func_name} returned {type(result).__name__}, expected file path(s). "
                    "Streaming tasks should return file paths, not in-memory data. "
                    "This may cause memory issues or database bloat.",
                    UserWarning,
                    stacklevel=2
                )
        
        duration = time.perf_counter() - start
        
        # Simple log without emoji (works in all terminals)
        print(f"[OK] {func_name} ({duration:.2f}s)")
        
        return result
    
    return wrapper


def timed_task(func: Callable) -> Callable:
    """Decorator to automatically log task execution time.
    
    Simpler than @streaming_task - only adds timing, no context management.
    
    Args:
        func: Task function to decorate
    
    Returns:
        Wrapped function with timing logs
    
    Example:
        @timed_task
        def slow_computation():
            time.sleep(5)
            return "result"
        
        # Output: slow_computation (5.01s)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        func_name = func.__name__
        
        try:
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start
            print(f"{func_name} ({duration:.2f}s)")
            return result
        except Exception as e:
            duration = time.perf_counter() - start
            print(f"[FAIL] {func_name} ({duration:.2f}s): {e}")
            raise
    
    return wrapper


def retry_task(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator to automatically retry tasks on failure.
    
    Note: This is separate from Queuack's built-in retry mechanism.
    Use this for transient errors within a single task execution
    (e.g., network requests, rate limits).
    
    Args:
        max_attempts: Maximum number of attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 1.0)
        backoff: Multiplier for delay after each retry (default: 2.0)
    
    Returns:
        Decorator function
    
    Example:
        @retry_task(max_attempts=5, delay=0.5, backoff=2.0)
        def fetch_api(url):
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        
        # Will retry up to 5 times with exponential backoff:
        # Attempt 1: immediate
        # Attempt 2: wait 0.5s
        # Attempt 3: wait 1.0s
        # Attempt 4: wait 2.0s
        # Attempt 5: wait 4.0s
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = func.__name__
            current_delay = delay
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        print(f"[FAIL] {func_name} failed after {max_attempts} attempts")
                        raise
                    
                    print(f"[RETRY] {func_name} attempt {attempt}/{max_attempts} failed: {e}")
                    print(f"        Retrying in {current_delay:.1f}s...")
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            # Should never reach here
            raise RuntimeError(f"{func_name} exceeded max attempts")
        
        return wrapper
    return decorator