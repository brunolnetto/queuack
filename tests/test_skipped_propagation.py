import pytest
from queuack.core import DuckQueue


# Reusable module-level functions for pickling


def noop():
    return None


def a_func():
    return "a"


def b_func():
    return "b"


def c_func():
    return "c"


def d_func():
    return "d"


@pytest.fixture
def queue(tmp_path):
    db = str(tmp_path / "test_skipped.duckdb")
    q = DuckQueue(db_path=db)
    return q
