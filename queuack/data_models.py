# file: data_models.py

"""queuack.data_models
======================

Lightweight dataclasses used across the Queuack project.

This module defines the canonical in-memory representations for jobs
and DAG nodes used by the queue core and the DAG engine. The main
types are:

- ``Job``: a serializable record persisted in the database (the
    attributes mirror the ``jobs`` table). Fields like ``func``,
    ``args`` and ``kwargs`` are stored as pickled bytes; consumers
    should only unpickle them when executing the job. ``Job`` also
    contains DAG-related metadata (``node_name``, ``dag_run_id``,
    ``dependency_mode``) which is optional and only used when the job
    is part of a DAG workflow.

- ``JobSpec``: a convenience value object used when enqueueing new
    work. This keeps user-level call-sites decoupled from the persisted
    ``Job`` representation (for example, ``JobSpec.func`` is a
    callable while ``Job.func`` is ``bytes``).

- ``DAGNode``: an in-memory node used by the DAG engine. ``DAGNode``
    intentionally uses ``id`` as the canonical identity: ``__hash__``
    and ``__eq__`` are defined based on ``id`` so nodes are stable when
    placed in sets or used as dictionary keys.

Important notes and best-practices
---------------------------------

- Picklability: functions passed to ``enqueue`` must be picklable
    (module-level callables). Tests should use module-level helper
    functions (not lambdas or nested functions) when creating jobs.

- Mutable defaults: fields that are mappings (for example
    ``DAGNode.metadata`` or ``JobSpec.kwargs``) use ``default_factory``
    or are normalized in ``__post_init__`` to avoid shared mutable
    defaults across instances.

- Minimal runtime dependencies: this module is intentionally
    lightweight and avoids importing queue core internals at import
    time. It only references enums and small types from
    ``queuack.status`` to keep typing expressive while preventing
    circular-import problems during package import.

This docstring should be sufficient for contributors to understand
the role of these dataclasses and to avoid common pitfalls (pickling
and mutable defaults). For schema-level documentation see the SQL
schema in ``queuack.core`` where the ``jobs`` table is created.
"""

import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .status import DependencyMode, NodeStatus

logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class Job:
    """
    Represents a serialized function call to be executed.

    Attributes:
        id: Unique job identifier
        func: Function to execute (serialized)
        args: Positional arguments
        kwargs: Keyword arguments
        queue: Queue name for routing
        status: Current job status
        priority: Higher = executed first (0-100)
        created_at: Job creation timestamp
        execute_after: Delay execution until this time
        claimed_at: When worker claimed the job
        claimed_by: Worker ID that claimed it
        completed_at: When job finished
        attempts: Number of execution attempts
        max_attempts: Maximum retry attempts
        timeout_seconds: Max execution time
        result: Serialized result (if successful)
        error: Error message (if failed)
    """

    id: str
    func: bytes  # Pickled function
    args: bytes  # Pickled args tuple
    kwargs: bytes  # Pickled kwargs dict
    queue: str
    status: str
    priority: int = 50
    created_at: datetime = None
    execute_after: datetime = None
    claimed_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0
    max_attempts: int = 3
    timeout_seconds: int = 300
    result: Optional[bytes] = None
    error: Optional[str] = None
    skipped_at: Optional[datetime] = None
    skip_reason: Optional[str] = None
    skipped_by: Optional[str] = None
    node_name: Optional[str] = None
    dag_run_id: Optional[str] = None
    dependency_mode: str = "all"  # 'all' or 'any'

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def execute(self, logger: Optional[logging.Logger] = None) -> Any:
        """
        Execute the job (unpickle function and call it).

        Args:
            logger: Optional logger to use for execution logging

        Returns:
            Function result

        Raises:
            Any exception from the function
        """
        if logger is None:
            logger = logging.getLogger(__name__)

        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)

        logger.info(f"Executing {func.__name__}(*{args}, **{kwargs})")

        return func(*args, **kwargs)


@dataclass
class JobSpec:
    """Specification for a job to be enqueued."""

    func: Callable
    args: Tuple = ()
    kwargs: Dict = None
    name: Optional[str] = None
    depends_on: Optional[Union[str, List[str]]] = None
    priority: int = 50
    max_attempts: int = 3
    timeout_seconds: int = 300
    dependency_mode: DependencyMode = DependencyMode.ALL

    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}


@dataclass
class DAGNode:
    """Represents a node (job) in the DAG."""

    id: str
    name: str
    status: NodeStatus = NodeStatus.PENDING
    dependency_mode: DependencyMode = DependencyMode.ALL
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, DAGNode) and self.id == other.id


class BackpressureError(Exception):
    """Raised when queue depth exceeds safe limits.

    Used to signal producers that the system is overloaded and enqueuing
    should be deferred or retried with backoff.
    """

    pass


class DAGValidationError(Exception):
    """Raised when DAG has structural problems (cycles, invalid nodes).

    This exception should be raised during DAG construction/validation
    and is not intended to be swallowed silently.
    """

    pass
