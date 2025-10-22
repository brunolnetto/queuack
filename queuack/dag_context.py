"""
DAG Context Manager for Queuack - Phase 2 Implementation

Provides a clean API for building and submitting DAGs atomically:

    with queue.dag("daily_etl") as dag:
        extract = dag.enqueue(extract_data, name="extract")
        transform = dag.enqueue(transform_data, depends_on="extract", name="transform")
        load = dag.enqueue(load_data, depends_on="transform", name="load")
    
    # DAG is validated and submitted atomically when context exits

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
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .status import DAGRunStatus, DependencyMode
from .exceptions import DAGValidationError
from .dag import DAGEngine
from .data_models import JobSpec

# ============================================================================
# Data Models
# ============================================================================

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
        fail_fast: bool = True
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
        dependency_mode: DependencyMode = DependencyMode.ALL
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
            dependency_mode=dependency_mode
        )
        
        # Reserve a job ID
        job_id = str(uuid.uuid4())
        self.jobs[name] = job_id
        self.job_specs[name] = spec
        
        # Add to validation engine
        self.engine.add_node(
            job_id,
            name=name,
            dependency_mode=dependency_mode
        )
        
        # Add dependencies to validation engine
        if depends_on:
            dep_list = [depends_on] if isinstance(depends_on, str) else depends_on
            for dep in dep_list:
                # Resolve dependency to job ID
                if dep in self.jobs:
                    parent_id = self.jobs[dep]
                elif self._is_valid_job_id(dep):
                    parent_id = dep
                else:
                    if self.fail_fast:
                        raise ValueError(
                            f"Dependency '{dep}' not found. "
                            f"Available nodes: {list(self.jobs.keys())}"
                        )
                    else:
                        continue
                
                # Add edge to validation graph
                try:
                    self.engine.add_dependency(job_id, parent_id)
                except DAGValidationError as e:
                    if self.fail_fast:
                        raise
                    else:
                        import warnings
                        warnings.warn(f"Validation error: {e}")
        
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
            self.queue.conn.execute("""
                INSERT INTO dag_runs (id, name, description, created_at, status)
                VALUES (?, ?, ?, ?, ?)
            """, [
                self.dag_run_id,
                self.name,
                self.description,
                datetime.now(),
                DAGRunStatus.RUNNING.value
            ])
            
            # Submit all jobs atomically
            for node_name, job_id in self.jobs.items():
                spec = self.job_specs[node_name]
                
                # Resolve dependencies to job IDs
                depends_on_ids = None
                if spec.depends_on:
                    dep_list = [spec.depends_on] if isinstance(spec.depends_on, str) else spec.depends_on
                    depends_on_ids = []
                    for dep in dep_list:
                        if dep in self.jobs:
                            depends_on_ids.append(self.jobs[dep])
                        elif self._is_valid_job_id(dep):
                            depends_on_ids.append(dep)
                
                # Insert job with DAG metadata
                self.queue.conn.execute("""
                    INSERT INTO jobs (
                        id, func, args, kwargs, queue, status, priority,
                        created_at, execute_after, max_attempts, timeout_seconds,
                        dag_run_id, node_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
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
                    spec.name
                ])
                
                # Insert dependencies
                if depends_on_ids:
                    for parent_id in depends_on_ids:
                        self.queue.conn.execute("""
                            INSERT INTO job_dependencies (child_job_id, parent_job_id)
                            VALUES (?, ?)
                        """, [job_id, parent_id])
        
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
            [id_to_name.get(job_id, job_id) for job_id in level]
            for level in levels
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
                            "DELETE FROM jobs WHERE dag_run_id = ?",
                            [self.dag_run_id]
                        )
                        self.queue.conn.execute(
                            "DELETE FROM dag_runs WHERE id = ?",
                            [self.dag_run_id]
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
            """, [self.dag_run_id]).fetchone()
            
            if result is None:
                raise ValueError(f"DAG run {self.dag_run_id} not found")
            
            return DAGRunStatus(result[0])
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs in this DAG run."""
        with self.queue._db_lock:
            results = self.queue.conn.execute("""
                SELECT id, node_name, status, created_at, completed_at
                FROM jobs
                WHERE dag_run_id = ?
                ORDER BY created_at
            """, [self.dag_run_id]).fetchall()
            
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'status': row[2],
                    'created_at': row[3],
                    'completed_at': row[4]
                }
                for row in results
            ]
    
    def get_progress(self) -> Dict[str, int]:
        """Get job counts by status."""
        with self.queue._db_lock:
            results = self.queue.conn.execute("""
                SELECT status, COUNT(*) as count
                FROM jobs
                WHERE dag_run_id = ?
                GROUP BY status
            """, [self.dag_run_id]).fetchall()
            
            progress = {
                'pending': 0,
                'claimed': 0,
                'done': 0,
                'failed': 0,
                'skipped': 0
            }
            
            for status, count in results:
                progress[status] = count
            
            return progress
    
    def is_complete(self) -> bool:
        """Check if DAG run is complete (all jobs done/failed/skipped)."""
        progress = self.get_progress()
        active = progress['pending'] + progress['claimed']
        return active == 0
    
    def update_status(self):
        """Update DAG run status based on job statuses."""
        # Still running
        if not self.is_complete():
            return
        
        progress = self.get_progress()
        
        # Determine final status
        if progress['failed'] > 0:
            final_status = DAGRunStatus.FAILED
        elif progress['done'] > 0:
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
                [final_status.value, datetime.now(), self.dag_run_id]
            )
