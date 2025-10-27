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

import inspect
import logging
import pickle
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .status import DependencyMode, NodeStatus


class NodeKind(Enum):
    JOB = "job"
    SUBDAG = "subdag"


@dataclass
class NodeType:
    """Represents the kind of a DAG node and provides helpers for
    auto-detection.

    Auto-detection heuristic:
    - If the callable has one or more positional parameters (e.g., a
      factory that accepts a queue), assume it's a SUBDAG factory.
    - Otherwise, assume it's a JOB.
    """

    kind: NodeKind = NodeKind.JOB

    @classmethod
    def detect(
        cls, func: Callable, explicit: Optional[Union[str, NodeKind]] = None
    ) -> "NodeType":
        # Honor explicit overrides
        if explicit is not None:
            if isinstance(explicit, NodeKind):
                return cls(kind=explicit)
            if isinstance(explicit, str):
                key = explicit.lower()
                if key == "subdag":
                    return cls(kind=NodeKind.SUBDAG)
                return cls(kind=NodeKind.JOB)
        # Heuristic-based auto-detection. Goals:
        # 1. Be conservative: prefer JOB unless there's a clear signal this is
        #    a sub-DAG factory (a function that accepts a queue and returns a DAG).
        # 2. Be explainable: check parameter name and annotation (if available).
        # 3. Avoid importing runtime queue types here to prevent circular
        #    imports; rely on naming/annotation hints instead.

        def _annotation_name(annotation) -> str:
            """Return a lower-cased, best-effort name for an annotation."""
            if annotation is inspect._empty:
                return ""
            try:
                # Common case: annotation is a type with __name__
                return getattr(annotation, "__name__", str(annotation)).lower()
            except Exception:
                return str(annotation).lower()

        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            # Builtins, C-extension callables or objects without an inspectable
            # signature should be treated as plain JOBs.
            return cls(kind=NodeKind.JOB)

        positional_params = [
            p
            for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]

        if not positional_params:
            # No positional parameters -> normal job function
            return cls(kind=NodeKind.JOB)

        first = positional_params[0]
        first_name = (first.name or "").lower()

        # Strong signal: parameter named like a queue
        queue_like_names = {"queue", "q", "duckqueue", "dq", "parent_queue"}
        if first_name in queue_like_names:
            return cls(kind=NodeKind.SUBDAG)

        # Secondary signal: parameter annotation mentions 'queue' or 'duckqueue'
        ann_name = _annotation_name(first.annotation)
        if ann_name and ("duckqueue" in ann_name or "queue" in ann_name):
            return cls(kind=NodeKind.SUBDAG)

        # No clear signals -> treat as JOB (conservative default)
        return cls(kind=NodeKind.JOB)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class TaskContext:
    """Context passed to every task execution.

    Provides access to parent task results and DAG metadata without
    requiring manual job ID passing.

    Attributes:
        job_id: Current job's ID
        queue_path: Path to DuckDB file
        dag_run_id: DAG run ID (if part of a DAG)
    """

    job_id: str
    queue_path: str
    dag_run_id: Optional[str] = None

    # Private fields for lazy loading
    _queue: Optional[Any] = field(default=None, repr=False)
    _parent_results: Dict[str, Any] = field(default_factory=dict, repr=False)
    _parent_ids: Optional[List[str]] = field(default=None, repr=False)

    @property
    def queue(self):
        """Lazy-load queue connection.

        Creates a DuckQueue instance on first access. Connection is reused
        for the lifetime of this context.
        """
        if self._queue is None:
            # Prefer the thread-local queue when available and pointing at the
            # same database path. This keeps ":memory:" DuckDB usage working
            # inside the same process/thread (same connection/visibility).
            import threading as _td

            thread_q = getattr(_td.current_thread(), "_queuack_queue", None)
            if (
                thread_q is not None
                and getattr(thread_q, "db_path", None) == self.queue_path
            ):
                self._queue = thread_q
            else:
                from queuack import DuckQueue

                self._queue = DuckQueue(self.queue_path)
        return self._queue

    def get_parent_result(self, parent_job_id: str) -> Any:
        """Get result from a specific parent task.

        Args:
            parent_job_id: Job ID of the parent task

        Returns:
            Unpickled result from parent task

        Raises:
            ValueError: If parent job not found or not complete

        Example:
            result = context.get_parent_result("abc123...")
        """
        if parent_job_id not in self._parent_results:
            self._parent_results[parent_job_id] = self.queue.get_result(parent_job_id)
        return self._parent_results[parent_job_id]

    def get_parent_results(self) -> List[Any]:
        """Get all parent task results (in dependency order).

        Returns:
            List of parent results, ordered by parent job ID

        Example:
            # Task with multiple parents
            def combine(context):
                parents = context.get_parent_results()
                return merge(parents)
        """
        if self._parent_ids is None:
            parent_ids = self.queue.conn.execute(
                """
                SELECT parent_job_id FROM job_dependencies
                WHERE child_job_id = ?
                ORDER BY parent_job_id
            """,
                [self.job_id],
            ).fetchall()

            self._parent_ids = [pid[0] for pid in parent_ids]

        return [self.get_parent_result(pid) for pid in self._parent_ids]

    def upstream(self, task_name: str) -> Any:
        """Get result from parent task by name.

        This is the recommended API for DAG tasks - cleaner and more
        readable than using job IDs.

        Args:
            task_name: Name of the upstream task (from dag.add_job(name=...))

        Returns:
            Result from the named upstream task

        Raises:
            ValueError: If no upstream task with that name exists

        Example:
            def transform(context):
                # Get result from task named "extract"
                data = context.upstream("extract")
                return process(data)
        """
        if not self.dag_run_id:
            raise ValueError(
                "upstream() requires DAG context. "
                "This job is not part of a DAG or dag_run_id is missing."
            )

        # Diagnostic: run the same query and log context to help debug
        # why parent lookups may fail in tests.
        params = [self.job_id, task_name, self.dag_run_id]
        try:
            result = self.queue.conn.execute(
                """
                SELECT j.id FROM jobs j
                JOIN job_dependencies jd ON jd.parent_job_id = j.id
                WHERE jd.child_job_id = ?
                    AND j.node_name = ?
                    AND j.dag_run_id = ?
            """,
                params,
            ).fetchone()
        except Exception as e:
            # On error, attach diagnostic info and re-raise
            print(f"DEBUG upstream query failed: params={params}, error={e}")
            raise
        # If the parent wasn't found it may be a transient visibility issue
        # (another connection inserted dependencies and committed just
        # now). Retry once after a very short sleep to reduce flakiness
        # in examples that use background workers or concurrent submitters.
        if result is None:
            try:
                import time as _time

                _time.sleep(0.01)
                result = self.queue.conn.execute(
                    """
                    SELECT j.id FROM jobs j
                    JOIN job_dependencies jd ON jd.parent_job_id = j.id
                    WHERE jd.child_job_id = ?
                        AND j.node_name = ?
                        AND j.dag_run_id = ?
                """,
                    params,
                ).fetchone()
            except Exception:
                # Ignore retry exceptions; we'll fall through to diagnostics
                result = None
        # If not found, also print available parent ids for the child and matching jobs
        if result is None:
            try:
                # Print diagnostic about queue path resolution
                import threading as _td

                thread_q = getattr(_td.current_thread(), "_queuack_queue", None)
                print(
                    f"DEBUG upstream: TaskContext.queue_path={self.queue_path}, thread_q.db_path={(getattr(thread_q, 'db_path', None))}, self.queue is thread_q? {self._queue is thread_q}"
                )

                parents = self.queue.conn.execute(
                    "SELECT parent_job_id FROM job_dependencies WHERE child_job_id = ?",
                    [self.job_id],
                ).fetchall()
                print(f"DEBUG upstream: child={self.job_id}, parents={parents}")
                for pid in [p[0] for p in parents]:
                    row = self.queue.conn.execute(
                        "SELECT id,node_name,dag_run_id,status FROM jobs WHERE id = ?",
                        [pid],
                    ).fetchone()
                    print(f"DEBUG parent row for {pid}: {row}")
            except Exception as e:
                print(f"DEBUG upstream additional inspect failed: {e}")

        if not result:
            raise ValueError(
                f"No upstream task named '{task_name}' found. "
                f"Available upstream tasks: {self.get_parent_names()}"
            )

        return self.get_parent_result(result[0])
    
    def upstream_all(self) -> Dict[str, Any]:
        """Get all parent task results as a dictionary.
        
        Returns a mapping of {task_name: result} for all upstream dependencies.
        This is useful when a task depends on multiple parents and needs to
        access them by name rather than order.
        
        Returns:
            Dict mapping parent task names to their results
        
        Raises:
            ValueError: If not part of a DAG or parent lookup fails
        
        Example:
            def combine_data(context):
                parents = context.upstream_all()
                
                # Access by name
                api_data = parents["fetch_api"]
                db_data = parents["fetch_db"]
                cache_data = parents.get("fetch_cache", None)  # Optional
                
                return merge(api_data, db_data, cache_data)
        
        Example - With validation:
            def aggregate(context):
                parents = context.upstream_all()
                
                required = {"extract_a", "extract_b", "extract_c"}
                missing = required - set(parents.keys())
                
                if missing:
                    raise ValueError(f"Missing upstream tasks: {missing}")
                
                return sum(parents.values())
        """
        if not self.dag_run_id:
            raise ValueError(
                "upstream_all() requires DAG context. "
                "This job is not part of a DAG or dag_run_id is missing."
            )
        
        parent_names = self.get_parent_names()
        return {name: self.upstream(name) for name in parent_names}
    
    def has_upstream_any(self, *task_names: str) -> bool:
        """Check if any of the specified upstream tasks exist.
        
        Args:
            *task_names: Variable number of task names to check
        
        Returns:
            True if at least one of the tasks exists upstream
        
        Example:
            def process(context):
                if context.has_upstream_any("cache", "fallback"):
                    # Use cached or fallback data
                    data = (context.upstream("cache") 
                           if context.has_upstream("cache") 
                           else context.upstream("fallback"))
                else:
                    # Fetch fresh data
                    data = fetch_from_source()
        """
        for name in task_names:
            if self.has_upstream(name):
                return True
        return False
    
    def upstream_or(self, task_name: str, default: Any = None) -> Any:
        """Get upstream result with a default fallback.
        
        Args:
            task_name: Name of upstream task
            default: Value to return if task doesn't exist
        
        Returns:
            Task result or default value
        
        Example:
            def process(context):
                # Use cached data if available, else None
                cached = context.upstream_or("cache", default=None)
                
                if cached:
                    return process_cached(cached)
                else:
                    return process_fresh()
        """
        try:
            return self.upstream(task_name)
        except (ValueError, KeyError):
            return default

    def get_parent_names(self) -> List[str]:
        """Get names of all parent tasks.

        Returns:
            List of parent task names

        Example:
            def task(context):
                print(f"Parents: {context.get_parent_names()}")
        """
        if not self.dag_run_id:
            return []

        if self._parent_ids is None:
            # Populate parent IDs first
            self.get_parent_results()

        names = []
        for pid in self._parent_ids:
            result = self.queue.conn.execute(
                """
                SELECT node_name FROM jobs WHERE id = ?
            """,
                [pid],
            ).fetchone()
            if result and result[0]:
                names.append(result[0])

        return names

    def has_upstream(self, task_name: str) -> bool:
        """Check if an upstream task exists.

        Args:
            task_name: Name to check

        Returns:
            True if upstream task exists, False otherwise

        Example:
            def task(context):
                if context.has_upstream("optional_preprocessing"):
                    data = context.upstream("optional_preprocessing")
                else:
                    data = load_default_data()
        """
        try:
            self.upstream(task_name)
            return True
        except ValueError:
            return False

    def close(self):
        """Close queue connection and cleanup resources.

        Automatically called when context exits. Normally you don't need
        to call this manually.
        """
        if self._queue is not None:
            try:
                self._queue.close()
            except Exception:
                pass
            self._queue = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup."""
        self.close()
        return False


def get_context() -> Optional[TaskContext]:
    """Get current task context from thread-local storage.

    Returns:
        TaskContext if currently executing within a task, None otherwise

    Example:
        def my_helper_function():
            context = get_context()
            if context:
                data = context.upstream("extract")
            else:
                data = load_from_config()
    """
    return getattr(threading.current_thread(), "_queuack_context", None)


def set_context(context: Optional[TaskContext]):
    """Set current task context (internal use).

    Args:
        context: TaskContext to set, or None to clear
    """
    if context is None:
        try:
            delattr(threading.current_thread(), "_queuack_context")
        except AttributeError:
            pass
    else:
        threading.current_thread()._queuack_context = context


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
    timeout_seconds: float = 300
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

        Automatically injects TaskContext if the function accepts a
        'context' or 'ctx' parameter. Context can be injected as:
        - Keyword argument (if function uses keyword-only or has defaults)
        - Positional argument (if signature requires it)

        Supports three patterns:
        1. task(context) - context only
        2. task(arg1, arg2, context) - args + context
        3. task(context, kwarg1=...) - context + kwargs

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

        func_name = getattr(func, "__name__", repr(func))

        # Get queue from thread-local (set by worker/claim)
        import threading

        queue = getattr(threading.current_thread(), "_queuack_queue", None)

        # Create context if queue is available
        context = None
        inject_context = False

        if queue is not None:
            try:
                context = TaskContext(
                    job_id=self.id, queue_path=queue.db_path, dag_run_id=self.dag_run_id
                )
                set_context(context)

                # Analyze function signature to determine injection strategy
                import inspect

                try:
                    sig = inspect.signature(func)

                    # Find context/ctx parameter
                    context_param_name = None
                    context_param = None

                    for param_name, param in sig.parameters.items():
                        if param_name in ("context", "ctx"):
                            context_param_name = param_name
                            context_param = param
                            break

                    if context_param_name and context_param:
                        # Determine injection strategy based on parameter kind
                        param_kind = context_param.kind

                        if param_kind == inspect.Parameter.POSITIONAL_ONLY:
                            # Positional-only: must inject as positional arg
                            # def task(context, /): ...
                            args = args + (context,)
                            inject_context = True
                            logger.info(
                                f"Executing {func_name} with positional context"
                            )

                        elif param_kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                            # Most common case: can be positional or keyword
                            # def task(context): ...
                            # def task(arg1, context): ...

                            # Check if context is already satisfied by positional args
                            params_list = list(sig.parameters.keys())
                            context_index = params_list.index(context_param_name)

                            if len(args) > context_index:
                                # Context position already filled by args - don't inject
                                logger.info(f"Executing {func_name} (context in args)")
                            else:
                                # Inject as keyword argument (safest)
                                kwargs = dict(kwargs, **{context_param_name: context})
                                inject_context = True
                                logger.info(
                                    f"Executing {func_name} with injected {context_param_name}"
                                )

                        elif param_kind == inspect.Parameter.KEYWORD_ONLY:
                            # Keyword-only: must inject as keyword
                            # def task(*, context): ...
                            kwargs = dict(kwargs, **{context_param_name: context})
                            inject_context = True
                            logger.info(
                                f"Executing {func_name} with keyword-only context"
                            )

                        elif param_kind == inspect.Parameter.VAR_POSITIONAL:
                            # *args - can't inject context here
                            logger.debug("Cannot inject context into *args parameter")

                        elif param_kind == inspect.Parameter.VAR_KEYWORD:
                            # **kwargs - context would be in kwargs already
                            logger.debug(
                                "Cannot inject context into **kwargs parameter"
                            )

                except (ValueError, TypeError) as e:
                    # Can't inspect signature (builtin, etc), skip injection
                    logger.debug(f"Could not inspect signature for {func_name}: {e}")

            except ImportError as e:
                # context module not available, skip injection
                logger.debug(f"Context module not available: {e}")
            except Exception as e:
                # Other errors in context creation, log but continue
                logger.warning(f"Error creating context for {func_name}: {e}")

        if not inject_context:
            logger.info(f"Executing {func_name}")

        try:
            # Enforce timeout if specified and "short" (< 60 seconds)
            # For longer timeouts, we skip thread-based enforcement to avoid
            # thread-safety issues with :memory: databases
            use_thread_timeout = (
                self.timeout_seconds
                and self.timeout_seconds > 0
                and self.timeout_seconds < 60
            )

            if use_thread_timeout:
                import threading
                import sys

                result_container = [None]
                exception_container = [None]

                def run_with_timeout():
                    try:
                        # Propagate context to timeout thread
                        if context:
                            set_context(context)
                        result_container[0] = self._execute_function(func, args, kwargs, logger)
                    except Exception as e:
                        exception_container[0] = e
                    finally:
                        # Clean up context in timeout thread
                        if context:
                            try:
                                set_context(None)
                            except Exception:
                                pass

                # Run in a thread with timeout
                thread = threading.Thread(target=run_with_timeout, daemon=True)
                thread.start()
                thread.join(timeout=self.timeout_seconds)

                if thread.is_alive():
                    # Timeout occurred
                    raise TimeoutError(f"Job exceeded timeout of {self.timeout_seconds} seconds")

                # Check if function raised an exception
                if exception_container[0]:
                    raise exception_container[0]

                result = result_container[0]
            else:
                result = self._execute_function(func, args, kwargs, logger)

            return result

        finally:
            # Cleanup context
            if context:
                try:
                    context.close()
                except Exception as e:
                    logger.debug(f"Error closing context: {e}")

                try:
                    set_context(None)
                except ImportError:
                    pass

    def _execute_function(self, func, args, kwargs, logger):
        """Execute the function with proper handling for SubDAGExecutor."""
        # CRITICAL FIX: SubDAGExecutor needs parent_job_id
        # Check if this is a SubDAGExecutor and inject parent_job_id
        from queuack.dag import SubDAGExecutor

        if isinstance(func, SubDAGExecutor):
            # Debug what we're dealing with
            logger.info(
                f"SubDAGExecutor - args: {args}, kwargs: {list(kwargs.keys()) if kwargs else 'None'}"
            )

            # The issue is that SubDAGExecutor.__call__(parent_job_id=None) expects parent_job_id
            # but we need to pass self.id. We must be careful about positional vs keyword args.

            if args and len(args) > 0:
                # If there are positional args, first one might conflict with parent_job_id
                logger.warning(
                    f"SubDAGExecutor called with positional args: {args}"
                )
                # Call as-is and let it fail for now to understand the issue
                result = func(*args, **kwargs)
            else:
                # No positional args - safe to pass parent_job_id as keyword arg
                kwargs_with_parent = dict(kwargs or {}, parent_job_id=self.id)
                result = func(**kwargs_with_parent)
        else:
            result = func(*args, **kwargs)
        return result


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
    timeout_seconds: float = 300
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
