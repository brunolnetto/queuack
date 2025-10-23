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
from .status import DAGRunStatus, DependencyMode, NodeStatus


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

    def export_mermaid(self) -> str:
        """
        Export DAG to Mermaid diagram format.

        Returns:
            Mermaid markdown string
        """
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
                style = ":::done"
            elif node.status == NodeStatus.FAILED:
                style = ":::failed"
            elif node.status == NodeStatus.SKIPPED:
                style = ":::skipped"
            elif node.status == NodeStatus.RUNNING:
                style = ":::running"
            elif node.status == NodeStatus.READY:
                style = ":::ready"

            lines.append(f'    {mermaid_id}["{label}"]{style}')

        # Add edges using original node IDs
        for parent, child in self.graph.edges:
            lines.append(f"    {parent} --> {child}")

        # Add style definitions
        lines.extend(
            [
                "",
                "    classDef done fill:#90EE90",
                "    classDef failed fill:#FFB6C6",
                "    classDef skipped fill:#D3D3D3",
                "    classDef running fill:#87CEEB",
                "    classDef ready fill:#FFD700",
            ]
        )

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

        # Create DAG run record
        with self.queue._db_lock:
            self.queue.conn.execute(
                """
                INSERT INTO dag_runs (id, name, description, created_at, status)
                VALUES (?, ?, ?, ?, ?)
            """,
                [
                    self.dag_run_id,
                    self.name,
                    self.description,
                    datetime.now(),
                    DAGRunStatus.RUNNING.value,
                ],
            )

            # Submit all jobs atomically
            for node_name, job_id in self.jobs.items():
                spec = self.job_specs[node_name]

                # Resolve dependencies to job IDs (internal names -> ids, plus any
                # external parents recorded earlier on the spec)
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

                # Include any external parent ids stored earlier (from enqueue time)
                ext = getattr(spec, "_external_parents", None)
                if ext:
                    depends_on_ids.extend(ext)

                # Deduplicate while preserving order
                seen = set()
                deduped = []
                for pid in depends_on_ids:
                    if pid not in seen:
                        seen.add(pid)
                        deduped.append(pid)
                depends_on_ids = deduped

                # Insert job with DAG metadata
                self.queue.conn.execute(
                    """
                    INSERT INTO jobs (
                        id, func, args, kwargs, queue, status, priority,
                        created_at, execute_after, max_attempts, timeout_seconds,
                        dag_run_id, node_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        job_id,
                        pickle.dumps(spec.func),
                        pickle.dumps(spec.args),
                        pickle.dumps(spec.kwargs),
                        self.queue.default_queue,
                        "pending",
                        spec.priority,
                        datetime.now(),
                        datetime.now(),
                        spec.max_attempts,
                        spec.timeout_seconds,
                        self.dag_run_id,
                        spec.name,
                    ],
                )

                # Insert dependencies
                if depends_on_ids:
                    for parent_id in depends_on_ids:
                        self.queue.conn.execute(
                            """
                            INSERT INTO job_dependencies (child_job_id, parent_job_id)
                            VALUES (?, ?)
                        """,
                            [job_id, parent_id],
                        )

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

    def export_mermaid(self) -> str:
        """
        Export DAG to Mermaid diagram format.

        Returns:
            Mermaid markdown string
        """
        return self.engine.export_mermaid()

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
                    with self.queue._db_lock:
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
        with self.queue._db_lock:
            result = self.queue.conn.execute(
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
        with self.queue._db_lock:
            results = self.queue.conn.execute(
                """
                SELECT id, node_name, status, created_at, completed_at
                FROM jobs
                WHERE dag_run_id = ?
                ORDER BY created_at
            """,
                [self.dag_run_id],
            ).fetchall()

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
        with self.queue._db_lock:
            results = self.queue.conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM jobs
                WHERE dag_run_id = ?
                GROUP BY status
            """,
                [self.dag_run_id],
            ).fetchall()

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

        with self.queue._db_lock:
            self.queue.conn.execute(
                """
                UPDATE dag_runs
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                [final_status.value, datetime.now(), self.dag_run_id],
            )
