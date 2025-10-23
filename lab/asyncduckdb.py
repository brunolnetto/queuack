import asyncio
import logging
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, List, Optional

import duckdb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Metrics for query performance tracking"""

    query: str
    execution_time: float
    rows_affected: int
    timestamp: datetime
    connection_wait_time: float = 0.0


class ConnectionHealthCheck:
    """Health check for database connections"""

    @staticmethod
    def is_healthy(conn: duckdb.DuckDBPyConnection) -> bool:
        """Check if connection is healthy"""
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            logger.error(f"Connection health check failed: {e}")
            return False


class AsyncDuckDB:
    """
    Production-grade asyncio wrapper for DuckDB with:
    - Connection pooling with health checks
    - Query metrics and performance tracking
    - Retry logic with exponential backoff
    - Query timeout support
    - Streaming results for large datasets
    - Query result caching
    - Prepared statement support
    """

    def __init__(
        self,
        database: str = ":memory:",
        max_workers: int = 4,
        read_only: bool = False,
        pool_size: int = 4,
        enable_metrics: bool = True,
        connection_timeout: float = 30.0,
        query_timeout: Optional[float] = None,
        enable_cache: bool = False,
        cache_size: int = 100,
    ):
        self.database = database
        self.read_only = read_only
        self.pool_size = pool_size
        self.enable_metrics = enable_metrics
        self.connection_timeout = connection_timeout
        self.query_timeout = query_timeout
        self.enable_cache = enable_cache

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="duckdb_worker"
        )
        self._closed = False

        # Connection pool
        self._connection_pool = Queue(maxsize=pool_size)
        self._is_memory = database == ":memory:"

        # Metrics tracking
        self._query_metrics: List[QueryMetrics] = []
        self._total_queries = 0
        self._failed_queries = 0

        # Query cache (simple LRU-like cache)
        self._query_cache: Dict[str, Any] = {}
        self._cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0

        # Initialize connections
        if self._is_memory:
            self._shared_conn = self._create_connection()
            logger.info(f"AsyncDuckDB initialized: {database} (shared connection)")
        else:
            for _ in range(pool_size):
                conn = self._create_connection()
                self._connection_pool.put(conn)
            logger.info(
                f"AsyncDuckDB initialized: {database} (pool_size={pool_size}, workers={max_workers})"
            )

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        """Create a new DuckDB connection with optimal settings"""
        conn = duckdb.connect(self.database, read_only=self.read_only)
        # Optimize connection settings
        conn.execute("SET threads TO 4")
        conn.execute("SET memory_limit = '2GB'")
        return conn

    def _get_connection(
        self, timeout: Optional[float] = None
    ) -> duckdb.DuckDBPyConnection:
        """Get a connection from pool with timeout"""
        start_time = time.time()

        if self._is_memory:
            return self._shared_conn

        timeout = timeout or self.connection_timeout
        try:
            conn = self._connection_pool.get(timeout=timeout)

            # Health check
            if not ConnectionHealthCheck.is_healthy(conn):
                logger.warning("Unhealthy connection detected, creating new one")
                conn.close()
                conn = self._create_connection()

            wait_time = time.time() - start_time
            if wait_time > 1.0:
                logger.warning(f"Connection wait time: {wait_time:.2f}s")

            return conn
        except Empty:
            raise TimeoutError(f"Could not acquire connection within {timeout}s")

    def _return_connection(self, conn: duckdb.DuckDBPyConnection):
        """Return connection to pool"""
        if not self._is_memory:
            self._connection_pool.put(conn)

    def _record_metrics(self, metrics: QueryMetrics):
        """Record query metrics"""
        if self.enable_metrics:
            self._query_metrics.append(metrics)
            # Keep only recent metrics
            if len(self._query_metrics) > 1000:
                self._query_metrics = self._query_metrics[-1000:]

    def _get_cache_key(self, query: str, parameters: Optional[tuple]) -> str:
        """Generate cache key for query"""
        return f"{query}::{parameters}"

    async def execute(
        self,
        query: str,
        parameters: Optional[tuple] = None,
        use_cache: bool = False,
        timeout: Optional[float] = None,
    ) -> List[tuple]:
        """
        Execute a query and return all results.

        Args:
            query: SQL query string
            parameters: Optional query parameters
            use_cache: Whether to use query cache
            timeout: Query timeout in seconds

        Returns:
            List of result tuples
        """
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        # Check cache
        if use_cache and self.enable_cache:
            cache_key = self._get_cache_key(query, parameters)
            if cache_key in self._query_cache:
                self._cache_hits += 1
                logger.debug(f"Cache hit for query: {query[:50]}...")
                return self._query_cache[cache_key]
            self._cache_misses += 1

        loop = asyncio.get_event_loop()
        timeout = timeout or self.query_timeout

        def _execute():
            start_time = time.time()
            conn = self._get_connection()
            try:
                if parameters:
                    result = conn.execute(query, parameters).fetchall()
                else:
                    result = conn.execute(query).fetchall()

                execution_time = time.time() - start_time

                # Record metrics
                self._record_metrics(
                    QueryMetrics(
                        query=query[:100],
                        execution_time=execution_time,
                        rows_affected=len(result),
                        timestamp=datetime.now(),
                    )
                )

                self._total_queries += 1

                # Update cache
                if use_cache and self.enable_cache:
                    cache_key = self._get_cache_key(query, parameters)
                    self._query_cache[cache_key] = result
                    # Simple cache size management
                    if len(self._query_cache) > self._cache_size:
                        # Remove oldest entry
                        self._query_cache.pop(next(iter(self._query_cache)))

                return result
            except Exception as e:
                self._failed_queries += 1
                logger.error(f"Query failed: {query[:50]}... Error: {e}")
                raise
            finally:
                self._return_connection(conn)

        if timeout:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, _execute), timeout=timeout
            )
        return await loop.run_in_executor(self.executor, _execute)

    async def execute_with_retry(
        self,
        query: str,
        parameters: Optional[tuple] = None,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> List[tuple]:
        """
        Execute query with exponential backoff retry logic.

        Args:
            query: SQL query string
            parameters: Optional query parameters
            max_retries: Maximum number of retry attempts
            backoff_factor: Multiplier for retry delay

        Returns:
            List of result tuples
        """
        last_exception = None

        for attempt in range(max_retries):
            try:
                return await self.execute(query, parameters)
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = backoff_factor**attempt
                    logger.warning(
                        f"Query failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Query failed after {max_retries} attempts")

        raise last_exception

    async def execute_streaming(
        self, query: str, chunk_size: int = 1000
    ) -> AsyncIterator[List[tuple]]:
        """
        Execute query and stream results in chunks (for large datasets).

        Args:
            query: SQL query string
            chunk_size: Number of rows per chunk

        Yields:
            Chunks of result tuples
        """
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()

        def _execute_batch(offset: int):
            conn = self._get_connection()
            try:
                paginated_query = f"{query} LIMIT {chunk_size} OFFSET {offset}"
                result = conn.execute(paginated_query).fetchall()
                return result
            finally:
                self._return_connection(conn)

        offset = 0
        while True:
            chunk = await loop.run_in_executor(self.executor, _execute_batch, offset)
            if not chunk:
                break
            yield chunk
            offset += chunk_size

    async def execute_df(self, query: str) -> Any:
        """Execute query and return pandas DataFrame"""
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()

        def _execute():
            conn = self._get_connection()
            try:
                return conn.execute(query).df()
            finally:
                self._return_connection(conn)

        return await loop.run_in_executor(self.executor, _execute)

    async def execute_many(
        self, query: str, parameters_list: List[tuple], batch_size: int = 1000
    ) -> None:
        """
        Execute query with multiple parameter sets in batches.

        Args:
            query: SQL query string
            parameters_list: List of parameter tuples
            batch_size: Number of parameters to process per batch
        """
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()

        # Process in batches for better performance
        for i in range(0, len(parameters_list), batch_size):
            batch = parameters_list[i : i + batch_size]

            def _execute():
                conn = self._get_connection()
                try:
                    conn.executemany(query, batch)
                finally:
                    self._return_connection(conn)

            await loop.run_in_executor(self.executor, _execute)

    async def fetch_one(
        self, query: str, parameters: Optional[tuple] = None
    ) -> Optional[tuple]:
        """Execute query and return first result"""
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()

        def _execute():
            conn = self._get_connection()
            try:
                if parameters:
                    result = conn.execute(query, parameters).fetchone()
                else:
                    result = conn.execute(query).fetchone()
                return result
            finally:
                self._return_connection(conn)

        return await loop.run_in_executor(self.executor, _execute)

    async def execute_script(self, script: str) -> None:
        """Execute multiple SQL statements"""
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()

        def _execute():
            conn = self._get_connection()
            try:
                for statement in script.split(";"):
                    statement = statement.strip()
                    if statement:
                        conn.execute(statement)
            finally:
                self._return_connection(conn)

        await loop.run_in_executor(self.executor, _execute)

    @asynccontextmanager
    async def transaction(self):
        """
        Async context manager for transactions with automatic rollback.
        """
        if self._closed:
            raise RuntimeError("AsyncDuckDB instance is closed")

        loop = asyncio.get_event_loop()
        conn_holder = {"conn": None}

        def _begin():
            conn = self._get_connection()
            conn.execute("BEGIN TRANSACTION")
            conn_holder["conn"] = conn
            return conn

        def _commit():
            if conn_holder["conn"]:
                conn_holder["conn"].execute("COMMIT")

        def _rollback():
            if conn_holder["conn"]:
                try:
                    conn_holder["conn"].execute("ROLLBACK")
                except Exception as e:
                    logger.error(f"Rollback failed: {e}")

        def _return():
            if conn_holder["conn"]:
                self._return_connection(conn_holder["conn"])

        class TransactionContext:
            def __init__(self, executor):
                self.executor = executor

            async def execute(self, query: str, params: Optional[tuple] = None):
                def _exec():
                    if params:
                        return conn_holder["conn"].execute(query, params).fetchall()
                    return conn_holder["conn"].execute(query).fetchall()

                return await loop.run_in_executor(self.executor, _exec)

        try:
            await loop.run_in_executor(self.executor, _begin)
            yield TransactionContext(self.executor)
            await loop.run_in_executor(self.executor, _commit)
        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            await loop.run_in_executor(self.executor, _rollback)
            raise
        finally:
            await loop.run_in_executor(self.executor, _return)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        if not self.enable_metrics:
            return {"error": "Metrics not enabled"}

        if not self._query_metrics:
            return {"total_queries": 0}

        execution_times = [m.execution_time for m in self._query_metrics]

        return {
            "total_queries": self._total_queries,
            "failed_queries": self._failed_queries,
            "success_rate": (self._total_queries - self._failed_queries)
            / max(self._total_queries, 1)
            * 100,
            "avg_execution_time": sum(execution_times) / len(execution_times),
            "min_execution_time": min(execution_times),
            "max_execution_time": max(execution_times),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits
            / max(self._cache_hits + self._cache_misses, 1)
            * 100,
            "recent_queries": len(self._query_metrics),
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on database"""
        try:
            start = time.time()
            await self.execute("SELECT 1")
            latency = time.time() - start

            return {
                "status": "healthy",
                "latency_ms": latency * 1000,
                "database": self.database,
                "pool_size": self.pool_size,
                "is_memory": self._is_memory,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Shutdown and cleanup resources"""
        if not self._closed:
            if self._is_memory:
                self._shared_conn.close()
            else:
                while not self._connection_pool.empty():
                    conn = self._connection_pool.get()
                    conn.close()

            self.executor.shutdown(wait=True)
            self._closed = True
            logger.info("AsyncDuckDB closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Advanced example usage
async def main():
    async with AsyncDuckDB(
        ":memory:", max_workers=4, enable_metrics=True, enable_cache=True, cache_size=50
    ) as db:
        # Health check
        health = await db.health_check()
        print(f"Health check: {health}\n")

        # Create table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name VARCHAR,
                email VARCHAR,
                created_at TIMESTAMP
            )
        """)

        # Bulk insert with batching
        users_data = [
            (i, f"User{i}", f"user{i}@example.com", "2024-01-01") for i in range(1, 101)
        ]
        await db.execute_many(
            "INSERT INTO users VALUES (?, ?, ?, ?)", users_data, batch_size=25
        )

        # Query with retry logic
        result = await db.execute_with_retry(
            "SELECT COUNT(*) FROM users", max_retries=3
        )
        print(f"Total users: {result[0][0]}\n")

        # Streaming large results
        print("Streaming results in chunks:")
        chunk_count = 0
        async for chunk in db.execute_streaming("SELECT * FROM users", chunk_size=20):
            chunk_count += 1
            print(f"  Chunk {chunk_count}: {len(chunk)} rows")
        print()

        # Cached query
        start = time.time()
        await db.execute("SELECT * FROM users WHERE id < 10", use_cache=True)
        first_time = time.time() - start

        start = time.time()
        await db.execute("SELECT * FROM users WHERE id < 10", use_cache=True)
        cached_time = time.time() - start

        print(f"First query: {first_time * 1000:.2f}ms")
        print(f"Cached query: {cached_time * 1000:.2f}ms\n")

        # Transaction with error handling
        try:
            async with db.transaction() as txn:
                await txn.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?)",
                    (101, "NewUser", "new@example.com", "2024-01-01"),
                )
                await txn.execute(
                    "UPDATE users SET name = ? WHERE id = ?", ("UpdatedUser", 1)
                )
        except Exception as e:
            print(f"Transaction failed: {e}")

        # Get performance metrics
        metrics = await db.get_metrics()
        print("Performance Metrics:")
        for key, value in metrics.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
