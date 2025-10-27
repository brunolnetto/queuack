"""
Decorators for common task patterns in Queuack.

This module provides convenience decorators that reduce boilerplate and
enforce best practices for specific task types.
"""

import asyncio
import inspect
import tempfile
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, Union
import time

from .data_models import TaskContext
from .streaming import StreamWriter


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


def generator_task(format: str = "jsonl", **kwargs):
    """Decorator for generator functions that stream large datasets.

    Automatically materializes generator output to a temporary file using
    StreamWriter, enabling O(1) memory usage for large datasets. The function
    returns the file path instead of the generator.

    This is ideal for ETL pipelines where intermediate results are too large
    to hold in memory.

    Args:
        format: Output format - 'jsonl', 'pickle', 'csv', or 'parquet'
            (default: 'jsonl')

    Returns:
        Decorator function

    Example - Basic generator task:
        @generator_task(format="jsonl")
        def extract_data():
            '''Extract 1 million records without loading all into memory.'''
            for i in range(1000000):
                yield {"id": i, "value": i * 2}

        # Returns: path to temporary JSONL file containing all records
        # Memory usage: O(1) - only one record in memory at a time

    Example - With database streaming:
        @generator_task(format="jsonl")
        def extract_from_db(context: TaskContext):
            '''Stream millions of rows from database.'''
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM large_table")

            for row in cursor:
                yield {
                    "id": row[0],
                    "name": row[1],
                    "value": row[2]
                }

            cursor.close()
            conn.close()

    Example - Chaining with StreamReader:
        from queuack import StreamReader

        @generator_task(format="jsonl")
        def transform(context: TaskContext):
            '''Transform data from upstream generator task.'''
            input_path = context.upstream("extract")

            # Read lazily - no memory spike
            reader = StreamReader(input_path)
            for item in reader:
                # Transform each item
                yield {
                    "id": item["id"],
                    "value": item["value"] * 10
                }

    Note:
        - Generator functions are auto-detected using inspect.isgeneratorfunction
        - Output written to temporary file (tempfile.NamedTemporaryFile)
        - Temporary files cleaned up by OS after process exits
        - Use with_timing=False in DAG to avoid duplicate timing logs
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Call the original function
            result = func(*args, **kwargs)

            # Check if result is a generator
            if inspect.isgenerator(result):
                # Create temporary file for output
                # delete=False so file persists after closing
                temp_file = tempfile.NamedTemporaryFile(
                    mode='wb',
                    suffix=f'.{format}',
                    delete=False
                )
                temp_path = temp_file.name
                temp_file.close()

                # Write generator to file
                writer = StreamWriter(temp_path, format=format)
                count = writer.write(result)

                print(f"[STREAM] {func.__name__} wrote {count:,} items to {Path(temp_path).name}")

                return temp_path
            else:
                # Not a generator - return as-is
                # This allows flexibility if function sometimes returns path directly
                return result

        return wrapper
    return decorator


def async_generator_task(format: str = "jsonl", **kwargs):
    """Decorator for async generator functions that stream large datasets.

    Like @generator_task but for async generators. Automatically materializes
    async generator output to a temporary file, enabling O(1) memory usage.

    Args:
        format: Output format - 'jsonl', 'pickle', 'csv', or 'parquet'
            (default: 'jsonl')

    Returns:
        Decorator function

    Example - Async API streaming:
        @async_generator_task(format="jsonl")
        async def fetch_api_data():
            '''Stream data from paginated API without loading all into memory.'''
            page = 1
            while True:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"/api/data?page={page}") as resp:
                        data = await resp.json()

                        if not data['items']:
                            break

                        for item in data['items']:
                            yield item

                        page += 1

    Example - Async database streaming:
        @async_generator_task(format="jsonl")
        async def extract_from_async_db():
            '''Stream records from async database.'''
            async with get_async_db_pool() as pool:
                async with pool.acquire() as conn:
                    async for row in conn.cursor("SELECT * FROM large_table"):
                        yield {
                            "id": row['id'],
                            "data": row['data']
                        }

    Example - Processing async streams:
        @async_generator_task(format="pickle")
        async def process_stream(context: TaskContext):
            '''Transform data from upstream async generator.'''
            input_path = context.upstream("extract")

            # Read with StreamReader
            from queuack import StreamReader
            reader = StreamReader(input_path)

            for item in reader:
                # Async processing
                processed = await async_transform(item)
                yield processed

    Note:
        - Async generator functions auto-detected using inspect.isasyncgenfunction
        - Returns path to temporary file containing materialized data
        - Use with DAG async execution for full async pipeline
        - Temporary files cleaned up by OS after process exits
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Call the original async function
            result = func(*args, **kwargs)

            # Check if result is an async generator
            if inspect.isasyncgen(result):
                # Create temporary file for output
                temp_file = tempfile.NamedTemporaryFile(
                    mode='wb',
                    suffix=f'.{format}',
                    delete=False
                )
                temp_path = temp_file.name
                temp_file.close()

                # Write async generator to file
                writer = StreamWriter(temp_path, format=format)
                count = 0

                # Manually iterate async generator and collect items
                items = []
                async for item in result:
                    items.append(item)

                # Write collected items
                def item_generator():
                    for item in items:
                        yield item

                count = writer.write(item_generator())

                print(f"[STREAM] {func.__name__} wrote {count:,} items to {Path(temp_path).name}")

                return temp_path
            else:
                # Not an async generator - await and return
                return await result

        return wrapper
    return decorator