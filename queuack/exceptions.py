class BackpressureError(Exception):
    """Raised when queue depth exceeds safe limits."""
    pass


class DAGValidationError(Exception):
    """Raised when DAG has structural problems."""
    pass
