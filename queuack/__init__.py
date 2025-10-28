from .core import (
    ConnectionPool,
    DuckQueue,
    Worker,
    WorkerPool,
    job,
)
from .dag import (
    DAG,
    DAGContext,
    DAGEngine,
    DAGRun,
)
from .data_models import (
    BackpressureError,
    DAGNode,
    DAGValidationError,
    Job,
    JobSpec,
    NodeKind,
    NodeType,
    TaskContext,
)
from .job_store import (
    DuckQueueAdapter,
    InMemoryJobStore,
)
from .status import (
    DAGRunStatus,
    DependencyMode,
    JobStatus,
    NodeStatus,
    job_status_to_node_status,
    node_status_to_job_status,
)
from .decorators import (
    streaming_task,
    timed_task,
    retry_task,
    generator_task,
    async_task,
    async_generator_task,
)
from .streaming import (
    StreamWriter,
    StreamReader,
)
from .mermaid_colors import (
    MermaidColorScheme,
)


__all__ = [
    # core exports
    "DuckQueue",
    "ConnectionPool",
    "Worker",
    "WorkerPool",
    "job",
    # data model exports
    "Job",
    "JobSpec",
    "DAGNode",
    "TaskContext",
    # dag exports
    "DAGEngine",
    # dag_context exports
    "DAGRun",
    "DAGContext",
    "DAG",
    # decorators exports
    "streaming_task",
    "timed_task",
    "retry_task",
    "generator_task",
    "async_task",
    "async_generator_task",
    # streaming exports
    "StreamWriter",
    "StreamReader",
    # mermaid exports
    "MermaidColorScheme",
    # status exports
    "DAGRunStatus",
    "NodeStatus",
    "DependencyMode",
    "job_status_to_node_status",
    "node_status_to_job_status",
    # job_store exports
    "InMemoryJobStore",
    "DuckQueueAdapter",
    # exceptions
    "DAGValidationError",
    "BackpressureError",
]

import threading

_process_queue = None
_process_queue_lock = threading.Lock()


def get_default_queue(db_path: str = "duckqueue.db") -> "DuckQueue":
    """Get or create the process-wide default queue.

    This ensures all DAGs and workers in the same process share
    one queue instance, avoiding lock conflicts.
    """
    global _process_queue

    with _process_queue_lock:
        if _process_queue is None:
            from .core import DuckQueue

            _process_queue = DuckQueue(db_path)
        return _process_queue


def close_default_queue():
    """Close the default queue (useful for cleanup in tests)."""
    global _process_queue

    with _process_queue_lock:
        if _process_queue is not None:
            _process_queue.close()
            _process_queue = None
