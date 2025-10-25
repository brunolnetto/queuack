"""Benchmark script for DAG submission performance.

Usage:
    python examples/bench_submission.py [--jobs N]

This will create a DAG with N jobs (one parent and N-1 children depending on it)
and measure the time taken by DAG.submit().
"""

import argparse
import time

from queuack import DAG, DuckQueue
from queuack.constants import VALUES_THRESHOLD


def noop():
    return 1


def build_and_submit(n_jobs: int, use_memory: bool = True) -> float:
    path = ":memory:" if use_memory else "bench.db"
    q = DuckQueue(path)
    try:
        dag = DAG("bench", q)
        dag.add_job(noop, name="parent")

        for i in range(n_jobs - 1):
            dag.add_job(noop, name=f"child_{i}", depends_on="parent")

        t0 = time.perf_counter()
        dag.submit()
        t1 = time.perf_counter()

        return t1 - t0
    finally:
        q.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--jobs",
        type=int,
        default=100,
        help="Number of jobs to create (including parent)",
    )
    p.add_argument(
        "--memory",
        action="store_true",
        help="Use in-memory DuckDB for the queue (default: file)",
    )
    args = p.parse_args()

    n = args.jobs
    print(f"VALUES_THRESHOLD = {VALUES_THRESHOLD}")
    print(f"Submitting DAG with {n} jobs...")
    elapsed = build_and_submit(n, use_memory=args.memory)
    print(f"Submit elapsed: {elapsed:.4f}s")


if __name__ == "__main__":
    main()
