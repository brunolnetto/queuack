"""Opinionated default constants for Queuack.

Keep conservative defaults here. Tests and callers may override behavior via
arguments or subclassing, but centralizing values avoids magic numbers spread
through the codebase.
"""

# Dependency insertion thresholds
# If dep row count is <= VALUES_THRESHOLD, use fast VALUES(...) INSERT path.
# Otherwise fall back to temp-table + chunked executemany to avoid huge SQL strings.
VALUES_THRESHOLD = 2000
DEP_CHUNK_SIZE = 1000

# Worker / DAG polling defaults
DEFAULT_POLL_TIMEOUT = 1.0

# Worker graceful drain seconds used when stopping workers to pick up remaining jobs
WORKER_DRAIN_SECONDS = 0.25

# Job defaults (kept in sync with DB schema defaults)
DEFAULT_PRIORITY = 50
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 300

# Backpressure thresholds (kept as defaults; DuckQueue classmethods may override)
BACKPRESSURE_WARNING_THRESHOLD = 1000
BACKPRESSURE_BLOCK_THRESHOLD = 10000
