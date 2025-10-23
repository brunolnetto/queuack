"""Small helpers for example scripts.

This module is intentionally small and lives under `examples/` to avoid
coupling example-only helpers with the main package. The function
`create_temp_path` returns a filesystem path under the OS temporary
directory with a UUID suffix so example runs don't conflict.
"""

import os
import tempfile
import uuid


def create_temp_path(prefix: str = "queuack") -> str:
    """Return a unique file path for a DuckDB database.

    Args:
        prefix: Optional prefix for the filename.

    Returns:
        Absolute path to a file in the system tmp directory.
    """
    name = f"{prefix}-{uuid.uuid4().hex}.db"
    return os.path.join(tempfile.gettempdir(), name)
