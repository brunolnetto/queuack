# file: dag.py

"""
Independent DAG resolution prototype for Queuack.

This module provides graph algorithms for dependency resolution WITHOUT
touching the queue implementation. Use this to validate the design before
integrating into queuack.py.

We leverage NetworkX for battle-tested graph algorithms rather than
reimplementing everything from scratch.

Features:
- Named nodes for readability
- String-based dependency references
- Automatic cycle detection
- DAG run tracking
- Atomic submission with rollback
"""

import os
import pickle
import uuid
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

import networkx as nx

from .data_models import DAGNode, DAGValidationError, JobSpec
from .job_store import JobStore
from .mermaid_colors import MermaidColorScheme
from .status import DAGRunStatus, DependencyMode, NodeStatus


def _subdag_sentinel(dag_run_id: str, queue_path: str):
    """Module-level sentinel function used to track sub-DAG completion.

    This function is picklable and will be enqueued as a regular job. When
    executed it resolves the correct queue (preferring the thread-local
    queue for in-memory databases) and checks the DAG run status.
    """

    from .core import DuckQueue

    # Create queue - auto-migration handles :memory: safety
    queue = DuckQueue(queue_path)

    try:
        dag_run = DAGRun(queue, dag_run_id)
        # Update status based on current job states
        dag_run.update_status()

        status = dag_run.get_status()
        progress = dag_run.get_progress()

        if status == DAGRunStatus.FAILED:
            raise RuntimeError(
                f"Sub-DAG failed (run_id={dag_run_id}): "
                f"{progress.get('done', 0)}/{sum(progress.values())} done, "
                f"{progress.get('failed', 0)} failed"
            )

        return dag_run_id
    finally:
        # Always close queue since we created it (auto-migration makes all paths safe)
        try:
            queue.close()
        except Exception:
            pass


class DAGEngine:
    """
    Core engine for DAG resolution using NetworkX.

    This handles:
    - Cycle detection
    - Topological sorting
    - Determining which nodes are ready to run
    - Failure propagation
    - Partial execution
    """

    def __init__(self, job_store: Optional[JobStore] = None):
        self.graph = nx.DiGraph()  # Directed graph
        self.nodes: Dict[str, DAGNode] = {}
        # Optional persistence adapter implementing JobStore
        self.job_store = job_store

    def add_node(
        self,
        node_id: str,
        name: str = None,
        dependency_mode: DependencyMode = DependencyMode.ALL,
        metadata: Dict[str, Any] = None,
    ) -> DAGNode:
        """Add a node to the DAG."""
        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists")

        node = DAGNode(
            id=node_id,
            name=name or node_id,
            dependency_mode=dependency_mode,
            metadata=metadata or {},
        )

        self.nodes[node_id] = node
        self.graph.add_node(node_id)

        return node

    def add_dependency(self, child_id: str, parent_id: str):
        """
        Add edge: parent -> child (child depends on parent).

        Raises:
            ValueError: If nodes don't exist or would create cycle
        """
        if child_id not in self.nodes:
            raise ValueError(f"Child node {child_id} does not exist")
        if parent_id not in self.nodes:
            raise ValueError(f"Parent node {parent_id} does not exist")

        # Add edge
        self.graph.add_edge(parent_id, child_id)

        # Check for cycles IMMEDIATELY
        if not nx.is_directed_acyclic_graph(self.graph):
            # Rollback the edge
            self.graph.remove_edge(parent_id, child_id)

            # Find the cycle for better error message
            try:
                cycle = nx.find_cycle(self.graph)
                cycle_str = " -> ".join([str(n) for n, _ in cycle])
                raise DAGValidationError(
                    f"Adding dependency {parent_id} -> {child_id} creates cycle: {cycle_str}"
                )
            except nx.NetworkXNoCycle:
                # Shouldn't happen, but fallback
                raise DAGValidationError(
                    f"Adding dependency {parent_id} -> {child_id} creates a cycle"
                )

    def validate(self) -> List[str]:
        """
        Validate the DAG structure.

        Returns:
            List of warning messages (empty if valid)

        Raises:
            DAGValidationError: If DAG is invalid
        """
        warnings = []

        # Check it's a DAG (no cycles)
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            cycle_strs = [" -> ".join(cycle) for cycle in cycles]
            raise DAGValidationError(f"DAG contains cycles: {cycle_strs}")

        # Check for orphaned nodes (no path to/from other nodes)
        if len(self.graph.nodes) > 1:
            weakly_connected = list(nx.weakly_connected_components(self.graph))
            if len(weakly_connected) > 1:
                warnings.append(
                    f"DAG has {len(weakly_connected)} disconnected components. "
                    "This may be intentional (parallel workflows)."
                )

        # Check for nodes with no parents (entry points)
        entry_nodes = [n for n in self.graph.nodes if self.graph.in_degree(n) == 0]
        if not entry_nodes:
            warnings.append("DAG has no entry points (all nodes have dependencies)")

        # Check for nodes with no children (terminal nodes)
        terminal_nodes = [n for n in self.graph.nodes if self.graph.out_degree(n) == 0]
        if not terminal_nodes:
            warnings.append("DAG has no terminal nodes (no final outputs)")

        return warnings

    def get_ready_nodes(self) -> List[DAGNode]:
        """
        Get all nodes that are ready to execute.

        A node is ready if:
        - Status is PENDING
        - ALL parent dependencies are met (based on dependency_mode)
        """
        ready = []

        for node_id, node in self.nodes.items():
            if node.status != NodeStatus.PENDING:
                continue

            # Get parent statuses
            parents = list(self.graph.predecessors(node_id))

            if not parents:
                # No dependencies, ready to run
                ready.append(node)
                continue

            parent_statuses = [self.nodes[p].status for p in parents]

            # Check dependency mode
            if node.dependency_mode == DependencyMode.ALL:
                # All parents must be DONE
                if all(s == NodeStatus.DONE for s in parent_statuses):
                    ready.append(node)

            elif node.dependency_mode == DependencyMode.ANY:
                # At least one parent must be DONE
                if any(s == NodeStatus.DONE for s in parent_statuses):
                    ready.append(node)

        return ready

    def mark_node_done(self, node_id: str):
        """Mark a node as successfully completed."""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")
        changed: List[str] = []

        # Only update if there's an actual change
        if self.nodes[node_id].status != NodeStatus.DONE:
            self.nodes[node_id].status = NodeStatus.DONE
            changed.append(node_id)

            # Persist change if adapter provided
            if self.job_store is not None:
                try:
                    # Map NodeStatus to JobStatus and persist
                    from queuack.status import node_status_to_job_status

                    job_status = node_status_to_job_status(NodeStatus.DONE)
                    self.job_store.update_job_status(node_id, status=job_status)
                except Exception:
                    # Adapter failures should not break in-memory engine
                    pass

        return changed

    def mark_node_failed(self, node_id: str, propagate: bool = True):
        """
        Mark a node as failed.

        Args:
            node_id: Node that failed
            propagate: If True, mark descendants as SKIPPED
        """
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        changed: List[str] = []

        if self.nodes[node_id].status != NodeStatus.FAILED:
            self.nodes[node_id].status = NodeStatus.FAILED
            changed.append(node_id)

            if self.job_store is not None:
                try:
                    from queuack.status import node_status_to_job_status

                    job_status = node_status_to_job_status(NodeStatus.FAILED)
                    self.job_store.update_job_status(node_id, status=job_status)
                except Exception:
                    pass

        if propagate:
            # Propagate failure to descendants, but only mark a descendant SKIPPED
            # when, given its dependency_mode and current parent statuses,
            # it can no longer possibly become ready. This preserves semantics
            # for DependencyMode.ANY where other parents may still succeed.
            # Compute descendants and process them in increasing distance from the failed node
            # so that immediate children are marked before their own children.
            descendants = nx.descendants(self.graph, node_id)
            if descendants:
                distances = nx.single_source_shortest_path_length(self.graph, node_id)
                # Filter to the descendants set and sort by distance (ascending)
                sorted_desc = sorted(
                    [n for n in distances.keys() if n in descendants],
                    key=lambda n: distances[n],
                )
            else:
                sorted_desc = []

            for desc_id in sorted_desc:
                desc_node = self.nodes[desc_id]
                # Only consider nodes that haven't finished/failed/skipped yet
                if desc_node.status not in [NodeStatus.PENDING, NodeStatus.READY]:
                    continue

                parents = list(self.graph.predecessors(desc_id))
                parent_statuses = [self.nodes[p].status for p in parents]

                to_skip = False
                if desc_node.dependency_mode == DependencyMode.ALL:
                    # For ALL, any parent failure or skip makes this node unsatisfiable
                    if any(
                        s in [NodeStatus.FAILED, NodeStatus.SKIPPED]
                        for s in parent_statuses
                    ):
                        to_skip = True

                elif desc_node.dependency_mode == DependencyMode.ANY:
                    # For ANY, only skip if all parents are FAILED or SKIPPED
                    if all(
                        s in [NodeStatus.FAILED, NodeStatus.SKIPPED]
                        for s in parent_statuses
                    ):
                        to_skip = True

                if to_skip:
                    desc_node.status = NodeStatus.SKIPPED
                    changed.append(desc_id)
                    if self.job_store is not None:
                        try:
                            from queuack.status import node_status_to_job_status

                            job_status = node_status_to_job_status(NodeStatus.SKIPPED)
                            self.job_store.update_job_status(
                                desc_id,
                                status=job_status,
                                skipped_at=None,
                                skip_reason=f"propagated from {node_id}",
                                skipped_by="dag-engine",
                            )
                        except Exception:
                            pass
        return changed

    def get_execution_order(self) -> List[List[str]]:
        """
        Get nodes in execution order (topological sort with levels).

        Returns:
            List of levels, where each level contains node IDs that can run in parallel

        Example:
            [[A, B], [C], [D, E]]
            Level 0: A and B can run in parallel
            Level 1: C runs after A and B complete
            Level 2: D and E run in parallel after C
        """
        if not nx.is_directed_acyclic_graph(self.graph):
            raise DAGValidationError("Cannot get execution order for graph with cycles")

        # Use NetworkX's built-in topological generations
        levels = list(nx.topological_generations(self.graph))

        return levels

    def get_parents(self, node_id: str) -> List[str]:
        """Get immediate parent node IDs."""
        return list(self.graph.predecessors(node_id))

    def get_children(self, node_id: str) -> List[str]:
        """Get immediate child node IDs."""
        return list(self.graph.successors(node_id))

    def get_ancestors(self, node_id: str) -> Set[str]:
        """Get all ancestor node IDs (transitive parents)."""
        return nx.ancestors(self.graph, node_id)

    def get_descendants(self, node_id: str) -> Set[str]:
        """Get all descendant node IDs (transitive children)."""
        return nx.descendants(self.graph, node_id)

    def get_critical_path(self) -> List[str]:
        """
        Get the longest path through the DAG (critical path).

        This is useful for estimating total execution time.
        """
        return nx.dag_longest_path(self.graph)

    def export_mermaid(self, color_scheme: Optional[MermaidColorScheme] = None) -> str:
        """
        Export DAG to Mermaid diagram format.

        Args:
            color_scheme: Optional custom color scheme. If None, uses default colors.

        Returns:
            Mermaid markdown string

        Example:
            Default colors:
            >>> dag.export_mermaid()

            Custom colors:
            >>> from queuack import MermaidColorScheme
            >>> dark = MermaidColorScheme.dark_mode()
            >>> dag.export_mermaid(color_scheme=dark)
        """
        if color_scheme is None:
            color_scheme = MermaidColorScheme.default()

        lines = ["graph TD"]

        # Create mapping from node_id to sanitized name for cleaner IDs
        def sanitize_name(name: str) -> str:
            """Convert name to valid Mermaid node ID."""
            return name.replace("_", "").replace("-", "").replace(" ", "")

        # Add nodes with styling based on status
        id_mapping = {}
        for node_id, node in self.nodes.items():
            # Use sanitized name as Mermaid node ID for cleaner output
            mermaid_id = sanitize_name(node.name)
            id_mapping[node_id] = mermaid_id
            label = node.name
            style = ""

            if node.status == NodeStatus.DONE:
                style = color_scheme.get_status_class("done")
            elif node.status == NodeStatus.FAILED:
                style = color_scheme.get_status_class("failed")
            elif node.status == NodeStatus.SKIPPED:
                style = color_scheme.get_status_class("skipped")
            elif node.status == NodeStatus.RUNNING:
                style = color_scheme.get_status_class("running")
            elif node.status == NodeStatus.READY:
                style = color_scheme.get_status_class("ready")
            elif node.status == NodeStatus.PENDING:
                style = color_scheme.get_status_class("pending")

            lines.append(f'    {mermaid_id}["{label}"]{style}')

        # Add edges using original node IDs
        for parent, child in self.graph.edges:
            lines.append(f"    {parent} --> {child}")

        # Add style definitions from color scheme
        lines.append("")
        lines.extend(color_scheme.get_style_definitions())

        return "\n".join(lines)

    def simulate_execution(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Simulate DAG execution (for testing).

        Returns:
            Execution statistics
        """
        stats = {
            "total_nodes": len(self.nodes),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "execution_levels": [],
        }

        levels = self.get_execution_order()

        for level_num, level_nodes in enumerate(levels):
            if verbose:
                print(f"\n=== Level {level_num} ===")

            level_stats = {"level": level_num, "nodes": []}

            for node_id in level_nodes:
                node = self.nodes[node_id]

                if node.status == NodeStatus.SKIPPED:
                    if verbose:
                        print(f"  SKIP: {node.name} (parent failed)")
                    stats["skipped"] += 1
                    level_stats["nodes"].append({"id": node_id, "status": "skipped"})
                    continue

                # Check if ready
                ready_nodes = self.get_ready_nodes()
                if node not in ready_nodes:
                    if verbose:
                        print(f"  WAIT: {node.name} (dependencies not met)")
                    continue

                # Simulate execution (mark as done or failed based on metadata)
                should_fail = node.metadata.get("simulate_failure", False)

                if should_fail:
                    if verbose:
                        print(f"  FAIL: {node.name}")
                    self.mark_node_failed(node_id, propagate=True)
                    stats["failed"] += 1
                    level_stats["nodes"].append({"id": node_id, "status": "failed"})
                else:
                    if verbose:
                        print(f"  DONE: {node.name}")
                    self.mark_node_done(node_id)
                    stats["completed"] += 1
                    level_stats["nodes"].append({"id": node_id, "status": "done"})

            stats["execution_levels"].append(level_stats)

        return stats


class SubDAGExecutor:
    """
    Executes a DAG factory function and links completion via sentinel job.
    """

    def __init__(
        self,
        dag_factory: Callable[[str], "DAG"],
        queue_path: str,
        poll_interval: float = 1.0,
        timeout: Optional[float] = None,
    ):
        self.dag_factory = dag_factory
        self.queue_path = queue_path
        self.poll_interval = poll_interval
        self.timeout = timeout

    @property
    def __name__(self) -> str:
        factory_name = getattr(self.dag_factory, "__name__", "unknown")
        return f"SubDAGExecutor({factory_name})"

    def __call__(self, parent_job_id: str = None):
        """
        Submit sub-DAG and create sentinel job for completion tracking.

        Returns the sub-DAG run_id immediately without blocking.
        """
        from .core import DuckQueue

        # Get queue reference - for SubDAGs, this should use the same database
        # as the parent DAG to maintain parent-child relationships
        queue = DuckQueue(self.queue_path)

        try:
            # Create and submit sub-DAG
            dag = self.dag_factory(queue)

            # Defensive validation and rewiring (existing code)
            if getattr(dag, "queue", None) is not queue:
                try:
                    queue.logger.warning(
                        "Sub-DAG factory returned a DAG that does not use the provided queue; "
                        "rewiring to use the parent's queue to preserve hierarchy"
                    )
                except Exception:
                    pass

                try:
                    own_q = getattr(dag, "queue", None)
                    if own_q is not None and hasattr(own_q, "close"):
                        try:
                            own_q.close()
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    dag.queue = queue
                    dag._owns_queue = False
                except Exception:
                    raise RuntimeError(
                        "Sub-DAG factory returned a DAG that could not be rewired to the provided queue"
                    )

            if parent_job_id:
                dag._parent_job_id = parent_job_id

            run_id = dag.submit()

            # Defensive: ensure dag_runs.parent_job_id is set
            try:
                if parent_job_id:
                    with queue.connection_context() as conn:
                        conn.execute(
                            "UPDATE dag_runs SET parent_job_id = ? WHERE id = ? AND (parent_job_id IS NULL OR parent_job_id = '')",
                            [parent_job_id, run_id],
                        )
                        conn.commit()
            except Exception:
                pass

            # Get all job IDs from the sub-DAG
            sub_job_ids = list(dag.jobs.values())

            # CRITICAL FIX: Reserve sentinel ID BEFORE rewiring
            import uuid

            sentinel_id = str(uuid.uuid4())

            # CRITICAL FIX: Rewire dependencies BEFORE enqueuing sentinel
            # This prevents workers from claiming downstream jobs prematurely
            if parent_job_id:
                try:
                    with queue.connection_context() as conn:
                        conn.execute(
                            """
                            UPDATE job_dependencies
                            SET parent_job_id = ?
                            WHERE parent_job_id = ?
                            """,
                            [sentinel_id, parent_job_id],
                        )
                        conn.commit()
                except Exception as e:
                    # Log but don't crash - downstream behavior may differ
                    try:
                        queue.logger.warning(
                            f"Failed to rewire dependencies for sub-DAG: {e}"
                        )
                    except Exception:
                        pass

            # Now enqueue sentinel with pre-allocated ID and rewired dependencies
            import pickle

            now = datetime.now()

            # Manually insert job with pre-allocated ID
            with queue.connection_context() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, func, args, kwargs, queue, status, priority,
                        created_at, execute_after, max_attempts, timeout_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        sentinel_id,
                        pickle.dumps(_subdag_sentinel),
                        pickle.dumps((run_id, self.queue_path)),
                        pickle.dumps({}),
                        queue.default_queue,
                        "pending",
                        100,  # High priority
                        now,
                        now,
                        3,
                        300,
                    ],
                )

                # Add dependencies: sentinel depends on all sub-DAG jobs
                if sub_job_ids:
                    dep_rows = [(sentinel_id, sub_job_id) for sub_job_id in sub_job_ids]
                    conn.executemany(
                        """
                        INSERT INTO job_dependencies (child_job_id, parent_job_id)
                        VALUES (?, ?)
                        """,
                        dep_rows,
                    )

                conn.commit()

            # If there are no background workers, execute synchronously
            if getattr(queue, "_worker_pool", None) is None:
                dag_run = DAGRun(queue, run_id)

                import time as _time

                try:
                    fast_mode = bool(int(os.getenv("QUEUACK_FAST_TESTS", "0")))
                except Exception:
                    fast_mode = False

                effective_poll = (
                    min(self.poll_interval, 0.01) if fast_mode else self.poll_interval
                )

                while not dag_run.is_complete():
                    j = queue.claim()
                    if j is None:
                        _time.sleep(effective_poll)
                        continue

                    try:
                        res = j.execute()
                        queue.ack(j.id, result=res)
                    except Exception as e:
                        queue.ack(j.id, error=f"{type(e).__name__}: {e}")

                    dag_run.update_status()

                final_status = dag_run.get_status()
                if final_status == DAGRunStatus.FAILED:
                    progress = dag_run.get_progress()
                    raise RuntimeError(
                        f"Sub-DAG '{dag.name}' failed. "
                        f"Progress: {progress.get('done', 0)}/{sum(progress.values())} jobs completed, "
                        f"{progress.get('failed', 0)} failed"
                    )

            return sentinel_id

        finally:
            # Always close queue since we created it (auto-migration makes all paths safe)
            try:
                queue.close()
            except Exception:
                pass


class DAGContext:
    """
    Context manager for building and submitting DAGs.

    Provides a fluent API for constructing complex workflows with named nodes,
    automatic dependency resolution, and validation before submission.

    Example:
        with queue.dag("etl_pipeline") as dag:
            # Add jobs with named references
            extract = dag.enqueue(extract_data, name="extract")

            # Reference by name
            transform = dag.enqueue(
                transform_data,
                name="transform",
                depends_on="extract"
            )

            # Multiple dependencies
            load = dag.enqueue(
                load_data,
                name="load",
                depends_on=["transform"]
            )

        # On exit: validated and submitted atomically
    """

    def __init__(
        self,
        queue: object,
        name: str,
        description: str = None,
        validate_on_exit: bool = True,
        fail_fast: bool = True,
    ):
        """
        Initialize DAG context.

        Args:
            queue: DuckQueue instance to submit jobs to
            name: Human-readable DAG name
            description: Optional DAG description
            validate_on_exit: If True, validate DAG before submission
            fail_fast: If True, raise immediately on validation errors
        """
        self.queue = queue
        self.name = name
        self.description = description
        self.validate_on_exit = validate_on_exit
        self.fail_fast = fail_fast

        # Generate unique run ID
        self.dag_run_id = str(uuid.uuid4())

        # Track jobs: name -> job_id
        self.jobs: Dict[str, str] = {}

        # Track job specs for validation
        self.job_specs: Dict[str, JobSpec] = {}

        # Build validation engine
        self.engine = DAGEngine()

        # Track submission state
        self._submitted = False
        self._validated = False
        # Track parent job if this context represents a sub-DAG
        self._parent_job_id = None

    def enqueue(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        name: Optional[str] = None,
        depends_on: Optional[Union[str, List[str]]] = None,
        priority: int = 50,
        max_attempts: int = 3,
        timeout_seconds: int = 300,
        dependency_mode: DependencyMode = DependencyMode.ALL,
    ) -> str:
        """
        Enqueue a job as part of this DAG.

        Args:
            func: Function to execute
            args: Positional arguments
            kwargs: Keyword arguments
            name: Human-readable node name (optional but recommended)
            depends_on: Parent node name(s) or job ID(s)
            priority: Job priority (0-100)
            max_attempts: Maximum retry attempts
            timeout_seconds: Execution timeout
            dependency_mode: ALL (default) or ANY for multiple dependencies

        Returns:
            Job ID (UUID)

        Raises:
            ValueError: If name already exists or dependencies not found
        """
        if self._submitted:
            raise RuntimeError("Cannot add jobs to already-submitted DAG")

        # Generate name if not provided
        if name is None:
            name = f"job_{len(self.jobs)}"

        # Check for duplicate names
        if name in self.jobs:
            raise ValueError(f"Job name '{name}' already exists in DAG")

        # Store spec for later submission
        spec = JobSpec(
            func=func,
            args=args,
            kwargs=kwargs or {},
            name=name,
            depends_on=depends_on,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            dependency_mode=dependency_mode,
        )

        # Reserve a job ID
        job_id = str(uuid.uuid4())
        self.jobs[name] = job_id
        self.job_specs[name] = spec

        # Add to validation engine
        self.engine.add_node(job_id, name=name, dependency_mode=dependency_mode)

        # Add dependencies to validation engine
        if depends_on:
            dep_list = [depends_on] if isinstance(depends_on, str) else depends_on
            # We'll resolve dependencies in two categories:
            # - internal parents (names that map to job IDs reserved in this DAG)
            # - external parents (explicit job IDs created outside this DAG)
            internal_parents = []
            external_parents = []

            for dep in dep_list:
                if dep in self.jobs:
                    internal_parents.append(self.jobs[dep])
                elif self._is_valid_job_id(dep):
                    # External job id: keep for DB insertion but do not add to engine
                    external_parents.append(dep)
                else:
                    if self.fail_fast:
                        raise ValueError(
                            f"Dependency '{dep}' not found. "
                            f"Available nodes: {list(self.jobs.keys())}"
                        )
                    else:
                        continue

            # Add only internal parents to the validation graph
            for parent_id in internal_parents:
                try:
                    self.engine.add_dependency(job_id, parent_id)
                except DAGValidationError as e:
                    if self.fail_fast:
                        raise
                    else:
                        import warnings

                        warnings.warn(f"Validation error: {e}")

            # Store external parents separately on the spec so submit() can insert them
            # without mutating the original human-friendly spec.depends_on.
            if external_parents:
                spec._external_parents = list(external_parents)

        return job_id

    def _is_valid_job_id(self, s: str) -> bool:
        """Check if string looks like a UUID job ID."""
        try:
            uuid.UUID(s)
            return True
        except (ValueError, AttributeError):
            return False

    def _prepare_job_data_for_submission(self):
        """Extract job preparation logic to reduce submit() complexity."""
        job_rows = []
        dep_rows = []

        # Use caches for pickled blobs to avoid redundant serialization
        pickled_func_cache = {}
        pickled_args_cache = {}
        pickled_kwargs_cache = {}
        created_at_now = datetime.now()

        for node_name, job_id in self.jobs.items():
            spec = self.job_specs[node_name]

            # Resolve dependencies
            depends_on_ids = []
            if spec.depends_on:
                dep_list = (
                    [spec.depends_on]
                    if isinstance(spec.depends_on, str)
                    else spec.depends_on
                )
                for dep in dep_list:
                    if dep in self.jobs:
                        depends_on_ids.append(self.jobs[dep])
                    elif self._is_valid_job_id(dep):
                        depends_on_ids.append(dep)

            # Add external parents if any
            ext = getattr(spec, "_external_parents", None)
            if ext:
                depends_on_ids.extend(ext)

            # Deduplicate dependencies
            depends_on_ids = list(dict.fromkeys(depends_on_ids))  # Preserves order

            # Handle SubDAGExecutor arguments
            args_to_store = spec.args
            try:
                if isinstance(spec.func, SubDAGExecutor):
                    args_to_store = (job_id,) + tuple(spec.args or ())
            except Exception:
                args_to_store = spec.args

            # Cache pickled objects to avoid redundant serialization
            func_key = id(spec.func)
            if func_key not in pickled_func_cache:
                pickled_func_cache[func_key] = pickle.dumps(spec.func)

            args_key = id(args_to_store)
            if args_key not in pickled_args_cache:
                pickled_args_cache[args_key] = pickle.dumps(args_to_store)

            kwargs_key = id(spec.kwargs)
            if kwargs_key not in pickled_kwargs_cache:
                pickled_kwargs_cache[kwargs_key] = pickle.dumps(spec.kwargs)

            if isinstance(spec.dependency_mode, str):
                dep_mode_value = spec.dependency_mode
            elif isinstance(spec.dependency_mode, DependencyMode):
                dep_mode_value = spec.dependency_mode.value
            else:
                dep_mode_value = DependencyMode.ALL.value

            job_rows.append(
                (
                    job_id,
                    pickled_func_cache[func_key],
                    pickled_args_cache[args_key],
                    pickled_kwargs_cache[kwargs_key],
                    self.queue.default_queue,
                    "pending",
                    spec.priority,
                    created_at_now,
                    created_at_now,
                    spec.max_attempts,
                    spec.timeout_seconds,
                    self.dag_run_id,
                    spec.name,
                    dep_mode_value,
                )
            )

            # Add dependency rows
            for parent_id in depends_on_ids:
                dep_rows.append((job_id, parent_id))

        return job_rows, dep_rows

    def validate(self) -> List[str]:
        """
        Validate DAG structure.

        Returns:
            List of warning messages (empty if valid)

        Raises:
            DAGValidationError: If DAG has structural problems
        """
        warnings = self.engine.validate()
        self._validated = True
        return warnings

    def submit(self) -> str:
        """
        Submit DAG to queue (called automatically on context exit).

        Returns:
            DAG run ID

        Raises:
            RuntimeError: If already submitted
            DAGValidationError: If validation fails
        """
        if self._submitted:
            raise RuntimeError("DAG already submitted")

        # Validate if not already done
        if self.validate_on_exit and not self._validated:
            warnings = self.validate()
            if warnings:
                import warnings as warn_module

                for warning in warnings:
                    warn_module.warn(f"DAG '{self.name}': {warning}")

        # Check if dag_run record already exists
        with self.queue.connection_context() as conn:
            existing = conn.execute(
                "SELECT id FROM dag_runs WHERE id = ?",
                [self.dag_run_id],
            ).fetchone()

            if not existing:
                conn.execute(
                    """
                    INSERT INTO dag_runs (id, name, description, created_at, status, parent_job_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    [
                        self.dag_run_id,
                        self.name,
                        self.description,
                        datetime.now(),
                        DAGRunStatus.RUNNING.value,
                        self._parent_job_id,
                    ],
                )

        # Prepare job and dependency data for bulk insert
        job_rows, dep_rows = self._prepare_job_data_for_submission()

        # Bulk insert jobs
        if job_rows:
            self.queue.conn.executemany(
                """
                INSERT INTO jobs (
                    id, func, args, kwargs, queue, status, priority,
                    created_at, execute_after, max_attempts, timeout_seconds,
                    dag_run_id, node_name, dependency_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                job_rows,
            )

        # CRITICAL FIX: Use unique temp table name to avoid collisions
        if dep_rows:
            from .constants import DEP_CHUNK_SIZE
            from .constants import VALUES_THRESHOLD as DEFAULT_VALUES_THRESHOLD

            queue_values_threshold = getattr(
                self.queue, "values_threshold", DEFAULT_VALUES_THRESHOLD
            )
            queue_chunk_size = getattr(self.queue, "dep_chunk_size", DEP_CHUNK_SIZE)

            CHUNK_SIZE = queue_chunk_size

            if len(dep_rows) <= queue_values_threshold:
                # Small dependency list: use VALUES-based INSERT
                placeholders = ", ".join(["(?,?)"] * len(dep_rows))
                params: List[str] = []
                for child, parent in dep_rows:
                    params.extend([child, parent])

                sql = f"""
                INSERT INTO job_dependencies (child_job_id, parent_job_id)
                SELECT v.child, v.parent FROM (VALUES {placeholders}) AS v(child, parent)
                LEFT JOIN job_dependencies jd
                ON jd.child_job_id = v.child AND jd.parent_job_id = v.parent
                WHERE jd.child_job_id IS NULL
                """

                self.queue.conn.execute(sql, params)
            else:
                # Large dependency list: use unique temp table
                import uuid

                # CRITICAL FIX: Unique temp table name per submission
                temp_table_name = f"__tmp_dep_inserts_{uuid.uuid4().hex[:12]}"

                try:
                    # Create unique temp table
                    self.queue.conn.execute(
                        f"""
                        CREATE TEMPORARY TABLE {temp_table_name} (
                            child_job_id TEXT, 
                            parent_job_id TEXT
                        )
                        """
                    )

                    insert_sql = f"INSERT INTO {temp_table_name} (child_job_id, parent_job_id) VALUES (?, ?)"

                    # Insert in chunks
                    for i in range(0, len(dep_rows), CHUNK_SIZE):
                        chunk = dep_rows[i : i + CHUNK_SIZE]
                        self.queue.conn.executemany(insert_sql, chunk)

                    # Insert distinct rows from temp table into job_dependencies
                    dedupe_sql = f"""
                    INSERT INTO job_dependencies (child_job_id, parent_job_id)
                    SELECT t.child_job_id, t.parent_job_id
                    FROM {temp_table_name} t
                    LEFT JOIN job_dependencies jd
                    ON jd.child_job_id = t.child_job_id AND jd.parent_job_id = t.parent_job_id
                    WHERE jd.child_job_id IS NULL
                    """

                    self.queue.conn.execute(dedupe_sql)
                finally:
                    # Drop unique temp table
                    try:
                        self.queue.conn.execute(
                            f"DROP TABLE IF EXISTS {temp_table_name}"
                        )
                    except Exception:
                        pass

        # Commit all changes
        try:
            self.queue.conn.commit()
        except Exception:
            pass

        self._submitted = True
        return self.dag_run_id

    def get_execution_order(self) -> List[List[str]]:
        """
        Get job names in execution order (topological levels).

        Returns:
            List of levels, where each level contains job names that can run in parallel
        """
        levels = self.engine.get_execution_order()

        # Map job IDs back to names
        id_to_name = {job_id: name for name, job_id in self.jobs.items()}

        return [
            [id_to_name.get(job_id, job_id) for job_id in level] for level in levels
        ]

    def export_mermaid(self, color_scheme: Optional[MermaidColorScheme] = None) -> str:
        """
        Export DAG to Mermaid diagram format.

        Args:
            color_scheme: Optional custom color scheme

        Returns:
            Mermaid markdown string
        """
        return self.engine.export_mermaid(color_scheme=color_scheme)

    def __enter__(self):
        """Enter context."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - submit DAG if no exceptions."""
        if exc_type is None and not self._submitted:
            try:
                self.submit()
            except Exception as e:
                # Rollback: delete any created jobs
                try:
                    self.queue.conn.execute(
                        "DELETE FROM jobs WHERE dag_run_id = ?", [self.dag_run_id]
                    )
                    self.queue.conn.execute(
                        "DELETE FROM dag_runs WHERE id = ?", [self.dag_run_id]
                    )
                except Exception:
                    pass
                raise e

        return False  # Don't suppress exceptions


class DAGRun:
    """Helper class for querying DAG run status."""

    def __init__(self, queue: object, dag_run_id: str):
        self.queue = queue
        self.dag_run_id = dag_run_id

    def get_status(self) -> DAGRunStatus:
        """Get current DAG run status."""
        with self.queue.connection_context() as conn:
            result = conn.execute(
                """
                SELECT status FROM dag_runs WHERE id = ?
            """,
                [self.dag_run_id],
            ).fetchone()

        if result is None:
            raise ValueError(f"DAG run {self.dag_run_id} not found")

        return DAGRunStatus(result[0])

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs in this DAG run."""
        with self.queue.connection_context() as conn:
            results = conn.execute(
                """
                SELECT id, node_name, status, created_at, completed_at
                FROM jobs
                WHERE dag_run_id = ?
                ORDER BY created_at
            """,
                [self.dag_run_id],
            ).fetchall()
            conn.commit()

        return [
            {
                "id": row[0],
                "name": row[1],
                "status": row[2],
                "created_at": row[3],
                "completed_at": row[4],
            }
            for row in results
        ]

    def get_progress(self) -> Dict[str, int]:
        """Get job counts by status."""
        with self.queue.connection_context() as conn:
            results = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM jobs
                WHERE dag_run_id = ?
                GROUP BY status
            """,
                [self.dag_run_id],
            ).fetchall()
            conn.commit()

        progress = {
            "pending": 0,
            "claimed": 0,
            "done": 0,
            "failed": 0,
            "skipped": 0,
        }

        for status, count in results:
            progress[status] = count

        return progress

    def is_complete(self) -> bool:
        """Check if DAG run is complete (all jobs done/failed/skipped)."""
        progress = self.get_progress()
        active = progress["pending"] + progress["claimed"]
        return active == 0

    def update_status(self):
        """Update DAG run status based on job statuses."""
        # Still running
        if not self.is_complete():
            return

        progress = self.get_progress()

        # Determine final status
        if progress["failed"] > 0:
            final_status = DAGRunStatus.FAILED
        elif progress["done"] > 0:
            final_status = DAGRunStatus.DONE
        else:
            # All skipped counts as failed
            final_status = DAGRunStatus.FAILED

        with self.queue.connection_context() as conn:
            conn.execute(
                """
                UPDATE dag_runs
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                [final_status.value, datetime.now(), self.dag_run_id],
            )

    def get_subdags(self) -> List["DAGRun"]:
        """
        Get all sub-DAG runs created by jobs in this DAG.

        Returns:
            List of DAGRun instances for child DAGs

        Example:
            main_run = DAGRun(queue, main_dag_run_id)

            for sub in main_run.get_subdags():
                print(f"Sub-DAG: {sub.get_status()}")
        """
        with self.queue.connection_context() as conn:
            # Find all jobs in this DAG
            job_ids = conn.execute(
                "SELECT id FROM jobs WHERE dag_run_id = ?", [self.dag_run_id]
            ).fetchall()
            conn.commit()

            if not job_ids:
                return []

            # Find DAG runs created by these jobs
            placeholders = ",".join("?" * len(job_ids))
            sub_runs = conn.execute(
                f"""
                SELECT id FROM dag_runs
                WHERE parent_job_id IN ({placeholders})
                ORDER BY created_at
                """,
                [jid[0] for jid in job_ids],
            ).fetchall()
            conn.commit()

        return [DAGRun(self.queue, run_id[0]) for run_id in sub_runs]

    def get_parent_job(self) -> Optional[str]:
        """
        Get parent job ID if this is a sub-DAG.

        Returns:
            Parent job ID or None if this is a top-level DAG
        """
        result = self.queue.conn.execute(
            "SELECT parent_job_id FROM dag_runs WHERE id = ?", [self.dag_run_id]
        ).fetchone()

        return result[0] if result and result[0] else None

    def get_hierarchy(self) -> Dict[str, Any]:
        """
        Get complete hierarchy including all sub-DAGs.

        Returns:
            Nested dict representing the execution tree

        Example:
            hierarchy = main_run.get_hierarchy()
            # {
            #   'dag_run_id': '...',
            #   'name': 'main',
            #   'status': 'done',
            #   'subdags': [
            #     {'dag_run_id': '...', 'name': 'etl_1', 'status': 'done', 'subdags': []},
            #     {'dag_run_id': '...', 'name': 'etl_2', 'status': 'done', 'subdags': []}
            #   ]
            # }
        """
        # Get this DAG's info
        with self.queue.connection_context() as conn:
            dag_info = conn.execute(
                "SELECT name, status FROM dag_runs WHERE id = ?", [self.dag_run_id]
            ).fetchone()

        hierarchy = {
            "dag_run_id": self.dag_run_id,
            "name": dag_info[0] if dag_info else "unknown",
            "status": dag_info[1] if dag_info else "unknown",
            "subdags": [],
        }

        # Recursively get sub-DAGs
        for sub in self.get_subdags():
            hierarchy["subdags"].append(sub.get_hierarchy())

        return hierarchy


class DAG:
    """
    A directed acyclic graph of jobs.

    The primary API for building complex workflows with dependency management.
    Provides a clean, symmetric interface to DuckQueue for orchestrating
    multi-step data pipelines, ETL workflows, and batch processing.

    Key Features:
    - Named jobs with dependency tracking
    - Automatic cycle detection
    - Topological execution ordering
    - Failure propagation with skip semantics
    - Status tracking and progress monitoring
    - Mermaid diagram export for visualization

    Example - Basic Pipeline:
        queue = DuckQueue("jobs.db")
        dag = DAG("etl_pipeline", queue)

        # Build workflow
        extract = dag.add_job(extract_data, name="extract")
        transform = dag.add_job(
            transform_data,
            name="transform",
            depends_on="extract"
        )
        load = dag.add_job(
            load_data,
            name="load",
            depends_on="transform"
        )

        # Submit and monitor
        dag.submit()
        print(f"Status: {dag.status}")
        print(f"Progress: {dag.progress}")

        # Wait for completion
        while not dag.is_complete():
            time.sleep(1)

    Example - Parallel Processing:
        dag = DAG("parallel_etl", queue)

        # Single extract
        extract = dag.add_job(extract_data, name="extract")

        # Parallel transforms
        t1 = dag.add_job(transform_type_a, name="transform_a", depends_on="extract")
        t2 = dag.add_job(transform_type_b, name="transform_b", depends_on="extract")
        t3 = dag.add_job(transform_type_c, name="transform_c", depends_on="extract")

        # Combined load (waits for all transforms)
        load = dag.add_job(
            load_all,
            name="load",
            depends_on=["transform_a", "transform_b", "transform_c"]
        )

        dag.submit()

    Example - ANY Dependency Mode:
        # Run downstream job if ANY upstream source succeeds
        dag = DAG("multi_source", queue)

        api1 = dag.add_job(fetch_api_1, name="api1")
        api2 = dag.add_job(fetch_api_2, name="api2")
        api3 = dag.add_job(fetch_api_3, name="api3")

        # Process runs if ANY API call succeeds
        process = dag.add_job(
            process_data,
            name="process",
            depends_on=["api1", "api2", "api3"],
            dependency_mode=DependencyMode.ANY
        )

        dag.submit()

    Example - Context Manager:
        with DAG("auto_submit", queue) as dag:
            dag.add_job(task1, name="t1")
            dag.add_job(task2, name="t2", depends_on="t1")
        # Auto-submitted on exit

    Attributes:
        name: Human-readable DAG name
        queue: Associated DuckQueue instance
        description: Optional DAG description
        dag_run_id: UUID of the DAG run (None until submitted)
        jobs: Dict mapping job names to job IDs
        status: Current DAG status (PENDING/RUNNING/DONE/FAILED)
        progress: Job counts by status
    """

    def __init__(
        self,
        name: str,
        queue: Optional[object] = None,
        description: Optional[str] = None,
        validate: Optional[bool] = True,
        fail_fast: Optional[bool] = True,
        timing: Optional[bool] = False,
    ):
        """Create a new DAG.

        Args:
            name: DAG name (used for tracking and logging)
            queue: DuckQueue instance to submit jobs to. If omitted or
                   set to None the DAG will create and own a DuckQueue
                   instance for its lifetime (start/stop workers and
                   close the DB connection on context exit).
            description: Optional human-readable description
            validate: If True, validate DAG structure before submission
            fail_fast: If True, raise immediately on validation errors
                       If False, log warnings but continue

        Example:
            queue = DuckQueue("jobs.db")
            dag = DAG("my_pipeline", queue, description="Daily ETL pipeline")
        """
        self.name = name
        self.description = description
        self._validate_on_submit = validate
        self._fail_fast = fail_fast
        self._timing_enabled = timing

        # If no queue was provided, create and own a DuckQueue instance so
        # the DAG can manage the queue lifecycle (start/stop workers,
        # close connections). If a queue is provided we do NOT manage its
        # lifecycle to avoid surprising side-effects on shared queue
        # instances.
        from .core import DuckQueue

        if queue is None:
            self.queue = DuckQueue()
            self._owns_queue = True
        else:
            self.queue = queue
            self._owns_queue = False

        # Delegate to DAGContext internally for now. Pass the resolved
        # queue object so submission and validation operate on the same
        # underlying queue/connection.
        self._context = DAGContext(
            queue=self.queue,
            name=name,
            description=description,
            validate_on_exit=False,  # We control submission explicitly
            fail_fast=fail_fast,
        )

        self._submitted = False
        self._dag_run = None  # Cached DAGRun helper
        self._parent_job_id = None  # Track parent if this is a sub-DAG

    def add_job(
        self,
        func: Callable,
        name: str = None,
        depends_on: Union[str, List[str]] = None,
        args: Tuple = (),
        kwargs: Dict = None,
        priority: int = 50,
        max_attempts: int = 3,
        timeout_seconds: int = 300,
        dependency_mode: DependencyMode = DependencyMode.ALL,
    ) -> str:
        """Add a job to the DAG.

        Jobs are not executed until submit() is called. Dependencies are
        resolved by name (for jobs in this DAG) or by job ID (for external jobs).

        Args:
            func: Function to execute (must be picklable)
            name: Job name (must be unique within DAG, auto-generated if None)
            depends_on: Parent job name(s) or ID(s). Can be:
                       - String: single dependency
                       - List[str]: multiple dependencies
                       - None: no dependencies (runs immediately)
            args: Positional arguments to pass to func
            kwargs: Keyword arguments to pass to func
            priority: Job priority (0-100, higher = runs first)
            max_attempts: Maximum retry attempts on failure
            timeout_seconds: Maximum execution time before timeout
            dependency_mode: How to handle multiple dependencies:
                           - DependencyMode.ALL: wait for all parents (default)
                           - DependencyMode.ANY: wait for any parent

        Returns:
            Job ID (UUID string)

        Raises:
            RuntimeError: If DAG already submitted
            ValueError: If job name already exists or dependency not found

        Example - Simple dependency:
            extract = dag.add_job(extract_data, name="extract")
            transform = dag.add_job(
                transform_data,
                name="transform",
                depends_on="extract"
            )

        Example - Multiple dependencies:
            load = dag.add_job(
                load_data,
                name="load",
                depends_on=["transform_a", "transform_b", "transform_c"]
            )

        Example - External dependency:
            # Job created outside this DAG
            external_id = queue.enqueue(prepare_data)

            # Reference it by ID
            process = dag.add_job(
                process_data,
                name="process",
                depends_on=external_id
            )

        Example - ANY mode:
            # Run if ANY API succeeds (fallback pattern)
            aggregate = dag.add_job(
                aggregate_data,
                name="aggregate",
                depends_on=["api1", "api2", "api3"],
                dependency_mode=DependencyMode.ANY
            )
        """
        # Backwards-compatible thin wrapper that delegates to the unified
        # `add_node` API. Kept to avoid breaking existing callsites.
        return self.add_node(
            func=func,
            name=name,
            kind="job",
            args=args,
            kwargs=kwargs,
            depends_on=depends_on,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            dependency_mode=dependency_mode,
        )

    def add_node(
        self,
        func: Callable,
        name: str = None,
        kind: Optional[Union[str, object]] = None,
        args: Tuple = (),
        kwargs: Dict = None,
        depends_on: Union[str, List[str]] = None,
        priority: int = 50,
        max_attempts: int = 3,
        timeout_seconds: int = 300,
        dependency_mode: DependencyMode = DependencyMode.ALL,
        **extras,
    ) -> str:
        """Unified API to add any DAG node.

        kind: NodeKind or string ("job" or "subdag"). If None, the node
        type will be auto-detected using `NodeType.detect` heuristics.
        For "subdag", `func` must be a module-level factory
        Callable[[DuckQueue], DAG]. The method will wrap the factory in a
        SubDAGExecutor internally to preserve existing semantics.
        """
        if self._submitted:
            raise RuntimeError(
                f"Cannot add nodes to DAG '{self.name}' - already submitted. "
                "Create a new DAG instance for additional workflows."
            )
        # Auto-detect or normalize NodeKind
        from .data_models import NodeKind, NodeType

        node_type = NodeType.detect(func, explicit=kind)

        # For subdags, wrap the provided factory in a SubDAGExecutor so the
        # existing submission machinery (which expects a callable job.func)
        # continues to work unchanged.
        if node_type.kind == NodeKind.SUBDAG:
            # Maintain previous default: parent sub-dag jobs are not retried
            # unless the caller explicitly overrides max_attempts.
            if max_attempts == 3:
                max_attempts = 1

            # Build executor with queue path and caller options
            poll_interval = extras.get("poll_interval", 1.0)
            timeout = extras.get("timeout", None)

            # SubDAGExecutor is defined earlier in this module; use it
            executor = SubDAGExecutor(
                dag_factory=func,
                queue_path=self.queue.db_path,
                poll_interval=poll_interval,
                timeout=timeout,
            )

            # Use the executor as the job func to preserve pickling and
            # execution behavior used by the submit machinery.
            job_func = executor
        else:
            job_func = func

        return self._context.enqueue(
            func=job_func,
            args=args,
            kwargs=kwargs,
            name=name,
            depends_on=depends_on,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            dependency_mode=dependency_mode,
        )

    def add_subdag(
        self,
        dag_factory: Callable[["DuckQueue"], "DAG"],
        name: str,
        depends_on: Union[str, List[str]] = None,
        poll_interval: float = 1.0,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> str:
        """
        Add a sub-DAG as a job.

        Args:
            dag_factory: Function(queue) -> DAG
                        Takes a DuckQueue and returns a DAG instance.
                        Must be module-level function (picklable).
            name: Job name
            depends_on: Dependencies
            poll_interval: Seconds between status checks
            timeout: Max seconds to wait for sub-DAG
            **kwargs: Additional job parameters

        Returns:
            Job ID

        Example:
            # Define factory function (module-level)
            def create_etl_dag(queue):
                dag = DAG("etl", queue)
                dag.add_job(extract, name="extract")
                dag.add_job(transform, name="transform", depends_on="extract")
                dag.add_job(load, name="load", depends_on="transform")
                return dag

            # Use in main DAG
            main = DAG("main", queue)
            etl1 = main.add_subdag(create_etl_dag, name="etl_1")
            etl2 = main.add_subdag(create_etl_dag, name="etl_2")
        """
        # CRITICAL WARNING: :memory: databases and SubDAGs
        # SubDAGs create separate DuckQueue instances, which for :memory: creates
        # isolated databases that break parent-child relationships.
        if self.queue.db_path == ":memory:":
            self.queue.logger.warning(
                "⚠️  SubDAGs with :memory: databases may not maintain proper parent-child "
                "relationships. Consider using a file-based database for SubDAG workflows."
            )

        executor = SubDAGExecutor(
            dag_factory=dag_factory,
            queue_path=self.queue.db_path,
            poll_interval=poll_interval,
            timeout=timeout,
        )
        # Sub-DAG parent jobs should not be retried by default since
        # re-running them would resubmit the sub-DAG and potentially
        # create duplicate work. Use max_attempts=1 unless caller
        # explicitly overrides it.
        if "max_attempts" not in kwargs:
            kwargs = dict(kwargs)
            kwargs["max_attempts"] = 1

        return self.add_job(executor, name=name, depends_on=depends_on, **kwargs)

    def submit(self) -> str:
        """Submit DAG to queue for execution.

        This atomically:
        1. Validates DAG structure (if validate=True)
        2. Creates DAG run record
        3. Inserts all jobs with dependencies
        4. Refreshes ready jobs cache

        Returns:
            DAG run ID (UUID)

        Raises:
            RuntimeError: If already submitted
            DAGValidationError: If validation fails (with fail_fast=True)

        Example:
            dag = DAG("pipeline", queue)
            dag.add_job(task1, name="t1")
            dag.add_job(task2, name="t2", depends_on="t1")

            run_id = dag.submit()
            print(f"Submitted as {run_id}")
        """
        if self._submitted:
            raise RuntimeError(
                f"DAG '{self.name}' already submitted with run_id={self.dag_run_id}"
            )

        # Validate structure if requested
        if self._validate_on_submit:
            warnings = self._context.validate()
            if warnings:
                import warnings as warn_module

                for w in warnings:
                    warn_module.warn(f"DAG '{self.name}': {w}", UserWarning)

        # Submit to queue via the internal DAGContext which will create the
        # dag_runs record and insert jobs atomically. Avoid duplicating the
        # dag_runs INSERT here to prevent extra work and potential UNIQUE
        # constraint errors when the context already created the record.
        dag_run_id = self._context.submit()
        self._submitted = True

        # Initialize DAGRun helper
        self._dag_run = DAGRun(self.queue, dag_run_id)

        parent_info = (
            f" (parent_job={self._parent_job_id[:8]})" if self._parent_job_id else ""
        )
        self.queue.logger.info(
            f"DAG '{self.name}' submitted: {len(self.jobs)} jobs, "
            f"run_id={self._context.dag_run_id[:8]}{parent_info}"
        )

        return dag_run_id

    def validate(self) -> List[str]:
        """Validate DAG structure without submitting.

        Checks for:
        - Cycles in dependency graph
        - Disconnected components (warning)
        - Missing entry points (warning)
        - Missing terminal nodes (warning)

        Returns:
            List of warning messages (empty if no warnings)

        Raises:
            DAGValidationError: If DAG has cycles or structural errors

        Example:
            dag = DAG("test", queue)
            dag.add_job(task1, name="t1")
            dag.add_job(task2, name="t2", depends_on="t1")

            warnings = dag.validate()
            if warnings:
                for w in warnings:
                    print(f"Warning: {w}")
        """
        return self._context.validate()
    
    def with_timing(self, enabled: bool = True) -> "DAG":
        """Enable automatic timing logs for all task executions.
        
        When enabled, each task will log its execution duration automatically.
        Useful for profiling pipelines and identifying bottlenecks.
        
        Args:
            enabled: If True, log timing for each task execution
        
        Returns:
            Self for method chaining
        
        Example:
            with DAG("pipeline").with_timing() as dag:
                dag.add_node(extract, name="extract")
                dag.add_node(transform, name="transform", depends_on="extract")
                dag.execute()
            
            # Output:
            # ✅ extract (0.15s)
            # ✅ transform (2.18s)
        """
        self._timing_enabled = enabled
        return self
    
    def execute(
        self,
        poll_interval: float = 0.1,
        timeout: Optional[float] = None,
        show_progress: bool = False,
    ) -> bool:
        """Execute DAG synchronously in the current process.
        
        This method processes jobs sequentially without background workers,
        making it ideal for:
        - Integration with external frameworks (PySpark, Dask, Ray)
        - Debugging and development
        - Environments where threading is problematic
        - Simple scripts that don't need parallelism
        
        Args:
            poll_interval: Seconds to wait between job claim attempts
            timeout: Maximum execution time in seconds (None = unlimited)
            show_progress: If True, print progress updates periodically
        
        Returns:
            True if DAG completed successfully, False if failed or timed out
        
        Raises:
            RuntimeError: If DAG not yet submitted
        
        Example - Basic usage:
            with DAG("pipeline") as dag:
                dag.add_node(extract, name="extract")
                dag.add_node(transform, name="transform", depends_on="extract")
            
            if dag.execute():
                print("Pipeline succeeded!")
            else:
                print(f"Pipeline failed: {dag.status}")
        
        Example - With progress:
            dag.execute(show_progress=True, poll_interval=0.5)
            # Progress: 2/5 jobs complete (40%)
            # Progress: 4/5 jobs complete (80%)
        
        Example - With timeout:
            if not dag.execute(timeout=300):
                print("Pipeline timed out after 5 minutes")
        """
        if not self._submitted:
            self.submit()
        
        import time
        
        start_time = time.perf_counter()
        last_progress_time = start_time
        progress_interval = 5.0  # Show progress every 5s
        
        while not self.is_complete():
            # Timeout check
            elapsed = time.perf_counter() - start_time
            if timeout and elapsed >= timeout:
                self.queue.logger.warning(
                    f"DAG '{self.name}' timed out after {timeout:.1f}s"
                )
                self.update_status()
                return False
            
            # Progress reporting
            if show_progress and (time.perf_counter() - last_progress_time) >= progress_interval:
                p = self.progress
                total = sum(p.values())
                done = p.get('done', 0)
                if total > 0:
                    pct = (done / total) * 100
                    print(f"Progress: {done}/{total} jobs complete ({pct:.0f}%)")
                last_progress_time = time.perf_counter()
            
            # Claim and execute next job
            job = self.queue.claim()
            if job:
                job_start = time.perf_counter()
                job_name = getattr(job, 'node_name', None) or job.id[:8]
                
                try:
                    result = job.execute(logger=self.queue.logger)
                    self.queue.ack(job.id, result=result)
                    
                    # Timing log if enabled
                    if self._timing_enabled:
                        duration = time.perf_counter() - job_start
                        print(f"✅ {job_name} ({duration:.2f}s)")
                
                except Exception as e:
                    import traceback
                    error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                    self.queue.ack(job.id, error=error)
                    
                    if self._timing_enabled:
                        duration = time.perf_counter() - job_start
                        print(f"❌ {job_name} failed ({duration:.2f}s)")
                    
                    self.queue.logger.error(f"Job {job_name} failed: {e}")
            else:
                time.sleep(poll_interval)
        
        # Final update
        self.update_status()
        
        # Show final progress if enabled
        if show_progress:
            p = self.progress
            total = sum(p.values())
            print(f"Complete: {p.get('done', 0)}/{total} succeeded, "
                  f"{p.get('failed', 0)} failed, {p.get('skipped', 0)} skipped")
        
        return self.status == DAGRunStatus.DONE

    @property
    def dag_run_id(self) -> Optional[str]:
        """Get DAG run ID.

        Returns None if DAG not yet submitted.

        Example:
            dag = DAG("test", queue)
            print(dag.dag_run_id)  # None

            dag.submit()
            print(dag.dag_run_id)  # UUID string
        """
        return self._context.dag_run_id if self._submitted else None

    @property
    def jobs(self) -> Dict[str, str]:
        """Get mapping of job names to job IDs.

        Returns:
            Dict[str, str]: {job_name: job_id}

        Example:
            dag = DAG("test", queue)
            extract = dag.add_job(extract_data, name="extract")
            transform = dag.add_job(transform_data, name="transform")

            print(dag.jobs)
            # {'extract': '<uuid>', 'transform': '<uuid>'}
        """
        return self._context.jobs.copy()

    @property
    def status(self) -> DAGRunStatus:
        """Get current DAG execution status.

        Returns:
            DAGRunStatus enum:
            - PENDING: Not yet submitted
            - RUNNING: Some jobs still executing
            - DONE: All jobs completed successfully
            - FAILED: At least one job failed permanently

        Example:
            dag = DAG("test", queue)
            print(dag.status)  # PENDING

            dag.submit()
            print(dag.status)  # RUNNING

            # ... jobs execute ...

            print(dag.status)  # DONE or FAILED
        """
        if not self._submitted:
            return DAGRunStatus.PENDING

        if self._dag_run is None:
            self._dag_run = DAGRun(self.queue, self._context.dag_run_id)

        return self._dag_run.get_status()

    @property
    def progress(self) -> Dict[str, int]:
        """Get job counts by status.

        Returns:
            Dict with keys: pending, claimed, done, failed, skipped

        Example:
            dag.submit()

            while not dag.is_complete():
                p = dag.progress
                print(f"Progress: {p['done']}/{len(dag.jobs)} complete")
                time.sleep(1)
        """
        if not self._submitted:
            return {
                "pending": len(self._context.jobs),
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "skipped": 0,
            }

        if self._dag_run is None:
            self._dag_run = DAGRun(self.queue, self._context.dag_run_id)

        return self._dag_run.get_progress()

    def is_complete(self) -> bool:
        """Check if all jobs have finished (success, failure, or skipped).

        Returns:
            True if no jobs are pending or claimed, False otherwise

        Example:
            dag.submit()

            while not dag.is_complete():
                print("Waiting for completion...")
                time.sleep(1)

            print(f"Final status: {dag.status}")
        """
        if not self._submitted:
            return False

        if self._dag_run is None:
            self._dag_run = DAGRun(self.queue, self._context.dag_run_id)

        return self._dag_run.is_complete()

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get detailed information about all jobs in this DAG.

        Returns:
            List of dicts with keys: id, name, status, created_at, completed_at

        Raises:
            RuntimeError: If DAG not yet submitted

        Example:
            dag.submit()

            for job in dag.get_jobs():
                print(f"{job['name']}: {job['status']}")
        """
        if not self._submitted:
            raise RuntimeError(
                f"DAG '{self.name}' not yet submitted. Call submit() first."
            )

        if self._dag_run is None:
            self._dag_run = DAGRun(self.queue, self._context.dag_run_id)

        return self._dag_run.get_jobs()

    def update_status(self):
        """Update DAG run status based on current job statuses.

        This checks if all jobs are complete and updates the DAG run
        status to DONE or FAILED accordingly.

        Typically called automatically, but can be called manually for
        immediate status refresh.

        Example:
            dag.submit()

            # ... jobs execute ...

            dag.update_status()
            print(dag.status)  # Updated status
        """
        if not self._submitted:
            return

        if self._dag_run is None:
            self._dag_run = DAGRun(self.queue, self._context.dag_run_id)

        self._dag_run.update_status()

    def get_execution_order(self) -> List[List[str]]:
        """Get jobs in topological execution order.

        Returns a list of "levels" where each level contains job names
        that can execute in parallel (no dependencies between them).

        Returns:
            List[List[str]]: Each inner list is a parallelizable level

        Example:
            dag = DAG("pipeline", queue)

            extract = dag.add_job(extract_data, name="extract")
            t1 = dag.add_job(transform_a, name="t1", depends_on="extract")
            t2 = dag.add_job(transform_b, name="t2", depends_on="extract")
            load = dag.add_job(load_data, name="load", depends_on=["t1", "t2"])

            order = dag.get_execution_order()
            print(order)
            # [['extract'], ['t1', 't2'], ['load']]

            # Level 0: extract runs first
            # Level 1: t1 and t2 run in parallel after extract
            # Level 2: load runs after both transforms
        """
        return self._context.get_execution_order()

    def export_mermaid(
        self,
        include_subdags: bool = True,
        max_depth: int = 3,
        color_scheme: Optional[MermaidColorScheme] = None
    ) -> str:
        """
        Export DAG structure as Mermaid diagram.

        Args:
            include_subdags: If True, expand sub-DAG jobs to show their structure
            max_depth: Maximum nesting depth to render (prevents infinite recursion)
            color_scheme: Optional custom color scheme for visualization

        Returns:
            Mermaid markdown string

        Example:
            # Simple diagram with default colors
            mermaid = dag.export_mermaid(include_subdags=False)

            # Full hierarchy with custom colors
            from queuack import MermaidColorScheme
            blue_scheme = MermaidColorScheme.blue_professional()
            mermaid = dag.export_mermaid(include_subdags=True, color_scheme=blue_scheme)
        """
        if not self._submitted or not include_subdags:
            # Use simple engine export
            return self._context.export_mermaid(color_scheme=color_scheme)

        # Complex: include sub-DAG structure
        return self._export_nested_mermaid(max_depth=max_depth, color_scheme=color_scheme)

    def _export_nested_mermaid(
        self,
        max_depth: int = 3,
        color_scheme: Optional[MermaidColorScheme] = None
    ) -> str:
        """Export with sub-DAG expansion."""
        if color_scheme is None:
            color_scheme = MermaidColorScheme.default()

        lines = ["graph TD"]

        # Track job->subdag mapping
        job_to_subdag = {}

        # Get all jobs in this DAG
        jobs = self.get_jobs()

        for job_info in jobs:
            job_id = job_info["id"]
            job_name = job_info["name"]

            # Check if this job spawned a sub-DAG
            subdags = self.queue.conn.execute(
                """
                SELECT id, name FROM dag_runs 
                WHERE parent_job_id = ?
                """,
                [job_id],
            ).fetchall()

            if subdags and max_depth > 0:
                # This is a sub-DAG job
                subdag_id, subdag_name = subdags[0]
                job_to_subdag[job_id] = subdag_id

                # Create subgraph
                lines.append(f'    subgraph {job_name}["{job_name} (sub-DAG)"]')

                # Get sub-DAG structure
                sub_run = DAGRun(self.queue, subdag_id)
                sub_jobs = sub_run.get_jobs()

                # Add sub-DAG jobs
                for sub_job in sub_jobs:
                    sub_id = sub_job["id"][:8]
                    sub_name = sub_job["name"]
                    sub_status = sub_job["status"]

                    style = self._get_mermaid_style(sub_status)
                    lines.append(f'        {sub_id}["{sub_name}"]{style}')

                # Add sub-DAG dependencies
                for sub_job in sub_jobs:
                    sub_id = sub_job["id"]

                    deps = self.queue.conn.execute(
                        """
                        SELECT parent_job_id FROM job_dependencies 
                        WHERE child_job_id = ?
                        """,
                        [sub_id],
                    ).fetchall()

                    for dep in deps:
                        parent_id = dep[0][:8]
                        lines.append(f"        {parent_id} --> {sub_id[:8]}")

                lines.append("    end")
            else:
                # Regular job
                style = self._get_mermaid_style(job_info["status"], color_scheme)
                short_id = job_id[:8]
                lines.append(f'    {short_id}["{job_name}"]{style}')

        # Add top-level dependencies
        for job_info in jobs:
            job_id = job_info["id"]

            deps = self.queue.conn.execute(
                """
                SELECT parent_job_id FROM job_dependencies 
                WHERE child_job_id = ?
                """,
                [job_id],
            ).fetchall()

            for dep in deps:
                parent_id = dep[0]
                child_id = job_id

                # Handle sub-DAG notation
                parent_label = job_to_subdag.get(parent_id, parent_id[:8])
                child_label = job_to_subdag.get(child_id, child_id[:8])

                lines.append(f"    {parent_label} --> {child_label}")

        # Add style definitions from color scheme
        lines.append("")
        lines.extend(color_scheme.get_style_definitions())

        return "\n".join(lines)

    def _get_mermaid_style(self, status: str, color_scheme: Optional[MermaidColorScheme] = None) -> str:
        """Get Mermaid style class for job status."""
        if color_scheme is None:
            color_scheme = MermaidColorScheme.default()

        # Map job statuses to color scheme statuses
        status_map = {
            "claimed": "running",
            "pending": "pending",
        }
        mapped_status = status_map.get(status, status)
        return color_scheme.get_status_class(mapped_status)

    def get_job(self, name_or_id: str) -> Optional["Job"]:
        """Get job by name or ID.

        Args:
            name_or_id: Job name (from this DAG) or job ID (UUID)

        Returns:
            Job object or None if not found

        Example:
            extract_id = dag.add_job(extract_data, name="extract")

            # Get by name
            job = dag.get_job("extract")

            # Get by ID
            job = dag.get_job(extract_id)

            print(job.status)
        """
        # Try as name first
        if name_or_id in self._context.jobs:
            job_id = self._context.jobs[name_or_id]
        else:
            job_id = name_or_id

        return self.queue.get_job(job_id)

    def wait_for_completion(
        self,
        timeout: Optional[float] = None,
        poll_interval: float = 1.0,
        callback: Optional[Callable[[Dict[str, int]], None]] = None,
    ) -> bool:
        """Block until DAG completes or timeout.

        Args:
            timeout: Maximum seconds to wait (None = wait forever)
            poll_interval: Seconds between status checks
            callback: Optional function called with progress dict on each poll

        Returns:
            True if completed, False if timed out

        Raises:
            RuntimeError: If DAG not yet submitted

        Example - Simple wait:
            dag.submit()
            dag.wait_for_completion()
            print(f"Done! Status: {dag.status}")

        Example - With timeout:
            dag.submit()
            if dag.wait_for_completion(timeout=300):
                print("Completed within 5 minutes")
            else:
                print("Timed out!")

        Example - With progress callback:
            def show_progress(p):
                total = sum(p.values())
                done = p['done']
                print(f"Progress: {done}/{total}")

            dag.submit()
            dag.wait_for_completion(callback=show_progress)
        """
        if not self._submitted:
            raise RuntimeError(
                f"DAG '{self.name}' not yet submitted. Call submit() first."
            )

        import time

        # Use a monotonic timer for timeout calculations to avoid
        # spurious timeouts if the system clock is adjusted.
        start_time = time.perf_counter()

        while not self.is_complete():
            if callback:
                try:
                    callback(self.progress)
                except Exception as e:
                    self.queue.logger.warning(f"Progress callback error: {e}")

            if timeout and (time.perf_counter() - start_time) >= timeout:
                return False

            time.sleep(poll_interval)

        # Final callback after completion
        if callback:
            try:
                callback(self.progress)
            except Exception:
                pass

        # Update final status
        self.update_status()

        return True

    # Context manager support
    def __enter__(self):
        """Enter context manager.

        If this DAG created its own `DuckQueue` (no queue was provided at
        construction) we also enter the queue context so background workers
        are started. When a queue was provided by the caller we do not touch
        its lifecycle.
        """
        if getattr(self, "_owns_queue", False):
            # Start/manage the queue for the duration of the DAG context.
            self.queue.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - auto-submit if no exceptions.

        If this DAG owns the queue (created it at init), we will also exit
        the queue context here to stop workers and close connections.
        """
        try:
            if exc_type is None and not self._submitted:
                try:
                    self.submit()
                except Exception as e:
                    self.queue.logger.error(f"DAG auto-submit failed: {e}")
                    raise
        finally:
            # If we created the queue, close/exit it now. Use the queue's
            # context manager to ensure proper shutdown. Do not close queues
            # that were provided by callers.
            if getattr(self, "_owns_queue", False):
                try:
                    self.queue.__exit__(exc_type, exc_val, exc_tb)
                except Exception:
                    # Swallow to avoid masking original exceptions; log instead.
                    try:
                        self.queue.logger.exception("Error while closing owned queue")
                    except Exception:
                        pass

        return False  # Don't suppress exceptions

    def __repr__(self) -> str:
        """String representation."""
        status_str = self.status.value if self._submitted else "not_submitted"
        job_count = len(self._context.jobs)
        return f"DAG(name='{self.name}', jobs={job_count}, status={status_str})"

    def __str__(self) -> str:
        """Human-readable string."""
        if not self._submitted:
            return f"DAG '{self.name}' ({len(self._context.jobs)} jobs, not submitted)"

        p = self.progress
        return (
            f"DAG '{self.name}' [{self.status.value}]: "
            f"{p['done']} done, {p['failed']} failed, "
            f"{p['pending']} pending, {p['skipped']} skipped"
        )
