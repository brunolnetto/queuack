"""Status mapping helpers between queue JobStatus and DAG NodeStatus.

Keep queue-level and DAG-level states separate but provide helpers to map
between the two at the boundary.
"""

from enum import Enum


class JobStatus(Enum):
    """Job lifecycle states."""

    PENDING = "pending"  # Waiting to be claimed
    CLAIMED = "claimed"  # Worker has claimed it
    DONE = "done"  # Successfully completed
    FAILED = "failed"  # Failed after max retries
    DELAYED = "delayed"  # Scheduled for future execution
    SKIPPED = "skipped"  # Skipped/abandoned due to parent failure


class NodeStatus(Enum):
    """Status of a node in the DAG."""

    PENDING = "pending"  # Not yet eligible to run
    READY = "ready"  # All dependencies met, can run now
    RUNNING = "running"  # Currently executing
    DONE = "done"  # Successfully completed
    FAILED = "failed"  # Failed execution
    SKIPPED = "skipped"  # Skipped due to parent failure


class DependencyMode(Enum):
    """How to handle multiple parent dependencies."""

    ALL = "all"  # All parents must succeed (default, AND logic)
    ANY = "any"  # At least one parent must succeed (OR logic)


class DAGRunStatus(Enum):
    """Status of a DAG run."""

    PENDING = "pending"  # DAG created but not submitted
    RUNNING = "running"  # Some jobs still executing
    DONE = "done"  # All jobs completed successfully
    FAILED = "failed"  # At least one job failed
    CANCELLED = "cancelled"  # DAG execution cancelled


def job_status_to_node_status(
    job_status: JobStatus, *, claimed_started: bool = False
) -> NodeStatus:
    """Map a JobStatus (DB/queue) to a NodeStatus (DAG engine).

    Args:
        job_status: JobStatus enum value
        claimed_started: If True, a CLAIMED job is considered RUNNING; otherwise treated as PENDING
    Returns:
        NodeStatus
    """
    if job_status == JobStatus.PENDING:
        return NodeStatus.PENDING
    if job_status == JobStatus.DELAYED:
        # Delayed jobs are still pending from a DAG perspective until execute_after
        return NodeStatus.PENDING
    if job_status == JobStatus.CLAIMED:
        return NodeStatus.RUNNING if claimed_started else NodeStatus.PENDING
    if job_status == JobStatus.DONE:
        return NodeStatus.DONE
    if job_status == JobStatus.FAILED:
        return NodeStatus.FAILED
    if job_status == JobStatus.SKIPPED:
        # SKIPPED jobs map to SKIPPED node status
        return NodeStatus.SKIPPED

    raise ValueError(f"Unsupported JobStatus: {job_status}")


def node_status_to_job_status(
    node_status: NodeStatus, *, map_skipped_to_failed: bool = True
) -> JobStatus:
    """Map a NodeStatus (DAG engine) to a JobStatus (DB/queue).

    Args:
        node_status: NodeStatus enum value
        map_skipped_to_failed: If True, SKIPPED maps to FAILED in the DB (useful for auditing);
            otherwise SKIPPED maps to FAILED as well (no DB-level SKIPPED state currently)
    Returns:
        JobStatus
    """
    if node_status in (NodeStatus.PENDING, NodeStatus.READY):
        return JobStatus.PENDING
    if node_status == NodeStatus.RUNNING:
        return JobStatus.CLAIMED
    if node_status == NodeStatus.DONE:
        return JobStatus.DONE
    if node_status == NodeStatus.FAILED:
        return JobStatus.FAILED
    if node_status == NodeStatus.SKIPPED:
        # Map SKIPPED to a dedicated JobStatus.SKIPPED for persistence/audit
        return JobStatus.SKIPPED

    raise ValueError(f"Unsupported NodeStatus: {node_status}")
