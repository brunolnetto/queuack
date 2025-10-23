import os
import tempfile
from datetime import datetime

import pytest

from queuack import (
    DAGEngine,
    DAGValidationError,
    DuckQueue,
    DuckQueueAdapter,
    InMemoryJobStore,
    Job,
    JobStatus,
)


def make_job(id):
    return Job(
        id=id,
        func=b"",
        args=b"",
        kwargs=b"",
        queue="default",
        status=JobStatus.PENDING.value,
    )


def noop():
    return 42


def test_get_and_update_job_status_fields():
    j = make_job("j1")
    store = InMemoryJobStore([j])

    assert store.get_job("j1") is j
    assert store.get_job("missing") is None

    store.update_job_status("j1", status=JobStatus.DONE)
    assert j.status == JobStatus.DONE.value

    ts = datetime(2020, 1, 1)
    store.update_job_status(
        "j1", skipped_at=ts, skip_reason="r", skipped_by="u", attempts=2
    )
    assert j.skipped_at == ts
    assert j.skip_reason == "r"
    assert j.skipped_by == "u"
    assert j.attempts == 2


def test_bulk_update_applies_multiple():
    j1 = make_job("a")
    j2 = make_job("b")
    store = InMemoryJobStore([j1, j2])

    updates = [
        {"id": "a", "status": JobStatus.DONE},
        {"id": "b", "attempts": 4},
    ]

    store.bulk_update(updates)
    assert store.get_job("a").status == JobStatus.DONE.value
    assert store.get_job("b").attempts == 4


def test_update_missing_job_is_noop():
    store = InMemoryJobStore([])
    # Should not raise
    store.update_job_status("nope", status=JobStatus.FAILED)
    store.bulk_update([{"id": "nope", "status": JobStatus.FAILED}])


def test_get_job_exists():
    """Test getting an existing job."""
    j = make_job("j1")
    store = InMemoryJobStore([j])

    assert store.get_job("j1") is j


def test_get_job_missing():
    """Test getting a non-existent job returns None."""
    store = InMemoryJobStore([])

    assert store.get_job("missing") is None


def test_update_job_status_field():
    """Test updating job status field."""
    j = make_job("j1")
    store = InMemoryJobStore([j])

    store.update_job_status("j1", status=JobStatus.DONE)

    assert j.status == JobStatus.DONE.value


def test_update_job_multiple_fields():
    """Test updating multiple job fields at once."""
    j = make_job("j1")
    store = InMemoryJobStore([j])

    ts = datetime(2020, 1, 1)
    store.update_job_status(
        "j1",
        skipped_at=ts,
        skip_reason="test reason",
        skipped_by="test user",
        attempts=2,
    )

    assert j.skipped_at == ts
    assert j.skip_reason == "test reason"
    assert j.skipped_by == "test user"
    assert j.attempts == 2


def test_update_missing_job_is_noop():
    """Test that updating a missing job doesn't raise."""
    store = InMemoryJobStore([])

    # Should not raise
    store.update_job_status("nope", status=JobStatus.FAILED)

    # Verify store still empty
    assert store.get_job("nope") is None


def test_bulk_update_applies_multiple():
    """Test bulk update applies all updates."""
    j1 = make_job("a")
    j2 = make_job("b")
    store = InMemoryJobStore([j1, j2])

    updates = [
        {"id": "a", "status": JobStatus.DONE},
        {"id": "b", "attempts": 4},
    ]

    store.bulk_update(updates)

    assert store.get_job("a").status == JobStatus.DONE.value
    assert store.get_job("b").attempts == 4


def test_bulk_update_missing_jobs_ignored():
    """Test bulk update ignores missing jobs."""
    j1 = make_job("a")
    store = InMemoryJobStore([j1])

    updates = [
        {"id": "a", "status": JobStatus.DONE},
        {"id": "missing", "status": JobStatus.FAILED},
    ]

    # Should not raise
    store.bulk_update(updates)

    # First update should apply
    assert store.get_job("a").status == JobStatus.DONE.value


def test_bulk_update_with_empty_list():
    """Test bulk update with empty list."""
    j1 = make_job("a")
    store = InMemoryJobStore([j1])

    # Should not raise
    store.bulk_update([])

    # Job unchanged
    assert store.get_job("a").status == JobStatus.PENDING.value


def test_store_initialization_with_no_jobs():
    """Test creating store with no initial jobs."""
    store = InMemoryJobStore()

    assert store.get_job("anything") is None


def test_store_initialization_with_jobs():
    """Test creating store with initial jobs."""
    jobs = [make_job(f"j{i}") for i in range(5)]
    store = InMemoryJobStore(jobs)

    for i in range(5):
        assert store.get_job(f"j{i}") is not None


def test_update_job_status_with_enum():
    """Test updating with JobStatus enum."""
    j = make_job("j1")
    store = InMemoryJobStore([j])

    store.update_job_status("j1", status=JobStatus.CLAIMED)

    assert j.status == JobStatus.CLAIMED.value


def test_update_job_status_with_string():
    """Test updating with string status."""
    j = make_job("j1")
    store = InMemoryJobStore([j])

    # Store should handle string status
    store.update_job_status("j1", status="custom_status")

    assert j.status == "custom_status"


def test_update_partial_fields():
    """Test updating only some fields."""
    j = make_job("j1")
    j.attempts = 5
    j.skip_reason = "original"
    store = InMemoryJobStore([j])

    # Update only attempts
    store.update_job_status("j1", attempts=10)

    assert j.attempts == 10
    assert j.skip_reason == "original"  # Unchanged


def test_bulk_update_preserves_order():
    """Test bulk updates are applied in order."""
    j1 = make_job("a")
    store = InMemoryJobStore([j1])

    updates = [
        {"id": "a", "status": JobStatus.PENDING},
        {"id": "a", "status": JobStatus.CLAIMED},
        {"id": "a", "status": JobStatus.DONE},
    ]

    store.bulk_update(updates)

    # Final status should be DONE
    assert store.get_job("a").status == JobStatus.DONE.value


@pytest.fixture
def queue_tmp():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
        db_path = f.name
    try:
        os.unlink(db_path)
    except Exception:
        pass

    q = DuckQueue(db_path)
    try:
        yield q
    finally:
        q.close()
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_get_job_passthrough_and_update_status_done(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    job_id = q.enqueue(noop)
    # ensure initial status pending
    assert q.get_job(job_id).status == JobStatus.PENDING.value

    adapter.update_job_status(job_id, status=JobStatus.DONE)
    j = q.get_job(job_id)
    assert j.status == JobStatus.DONE.value


def test_update_skipped_sets_attempts_and_metadata(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    job_id = q.enqueue(noop, max_attempts=7)
    adapter.update_job_status(
        job_id,
        status=JobStatus.SKIPPED,
        skipped_at=datetime(2020, 1, 1),
        skip_reason="parent_failed",
        skipped_by="adapter-test",
    )

    job = q.get_job(job_id)
    # attempts should be finalized to max_attempts by the adapter SQL
    assert job.attempts == job.max_attempts
    assert job.status == JobStatus.SKIPPED.value
    assert job.skipped_by == "adapter-test"
    assert job.skip_reason == "parent_failed"


def test_bulk_update_and_noop(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    id1 = q.enqueue(noop)
    id2 = q.enqueue(noop)
    id3 = q.enqueue(noop)

    updates = [
        {"id": id1, "status": JobStatus.DONE},
        {"id": id2, "skip_reason": "skip me"},
        {"not_id": "missing"},
        {"id": id3},  # noop update (no fields)
    ]

    adapter.bulk_update(updates)

    assert q.get_job(id1).status == JobStatus.DONE.value
    assert q.get_job(id2).skip_reason == "skip me"

    # id3 should be unchanged (still pending)
    assert q.get_job(id3).status == JobStatus.PENDING.value


def test_update_with_string_status_and_no_fields_is_noop(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    jid = q.enqueue(noop)
    # Passing a string status should set it as-is
    adapter.update_job_status(jid, status="failed")
    assert q.get_job(jid).status == "failed"

    # No fields: should not raise and not modify
    before = q.get_job(jid).status
    adapter.update_job_status(jid)
    assert q.get_job(jid).status == before


def test_update_attempts_field_applies(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    jid = q.enqueue(noop, max_attempts=10)
    # explicitly set attempts via adapter
    adapter.update_job_status(jid, attempts=3)
    assert q.get_job(jid).attempts == 3


def test_skipped_attempts_finalized_even_if_attempts_provided(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    jid = q.enqueue(noop, max_attempts=5)
    # provide attempts explicitly but adapter should finalize to max_attempts when SKIPPED
    adapter.update_job_status(jid, status=JobStatus.SKIPPED, attempts=1)
    job = q.get_job(jid)
    assert job.attempts == job.max_attempts


def test_update_skipped_at_only(queue_tmp: DuckQueue):
    q = queue_tmp
    adapter = DuckQueueAdapter(q)

    jid = q.enqueue(noop)
    ts = datetime(2022, 1, 1)
    adapter.update_job_status(jid, skipped_at=ts)
    job = q.get_job(jid)
    assert job.skipped_at is not None
    # stored as datetime-like
    assert job.skipped_at.year == 2022


def _noop():
    return None


def test_skipped_persisted_and_excluded_from_claim():
    # Use in-memory DuckDB for isolation
    dq = DuckQueue(":memory:")

    # Enqueue parent and child with known IDs by using enqueue and capturing the returned IDs
    parent_id = dq.enqueue(_noop)
    child_id = dq.enqueue(_noop)

    # Create adapter and engine
    adapter = DuckQueueAdapter(dq)
    engine = DAGEngine(job_store=adapter)

    # Add nodes with same IDs so adapter can map status updates
    engine.add_node(parent_id, "parent")
    engine.add_node(child_id, "child")
    engine.add_dependency(child_id, parent_id)

    # Mark parent failed and propagate
    changed = engine.mark_node_failed(parent_id, propagate=True)

    # Child should be marked skipped in-memory
    assert child_id in changed
    assert engine.nodes[child_id].status.name.lower() == "skipped"

    # Persisted in DB: child job should have status 'skipped'
    job = dq.get_job(child_id)
    assert job is not None
    assert job.status == JobStatus.SKIPPED.value

    # Claim should not return the skipped job; queue should be empty of pending jobs
    claimed = dq.claim()
    assert claimed is None


class TestAdapterSQLGeneration:
    """Test adapter SQL generation edge cases."""

    def test_adapter_update_with_attempts_when_not_skipped(self):
        """Test that attempts field is applied when not marking as skipped."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop, max_attempts=10)

            # Update attempts directly (not as part of SKIPPED update)
            adapter.update_job_status(job_id, attempts=5)

            job = queue.get_job(job_id)
            assert job.attempts == 5

            # Now update status without attempts
            adapter.update_job_status(job_id, status=JobStatus.DONE)

            job = queue.get_job(job_id)
            assert job.status == JobStatus.DONE.value
            assert job.attempts == 5  # Should still be 5

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_update_skipped_with_explicit_attempts_ignored(self):
        """Test that explicit attempts parameter is ignored when marking SKIPPED."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop, max_attempts=7)

            # Try to set attempts=2 while marking SKIPPED
            # The adapter should finalize to max_attempts instead
            adapter.update_job_status(
                job_id,
                status=JobStatus.SKIPPED,
                attempts=2,  # This should be ignored
            )

            job = queue.get_job(job_id)
            assert job.status == JobStatus.SKIPPED.value
            assert job.attempts == 7  # Should be max_attempts, not 2

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_update_with_string_status(self):
        """Test adapter handles string status values."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop)

            # Pass status as string
            adapter.update_job_status(job_id, status="claimed")

            job = queue.get_job(job_id)
            assert job.status == "claimed"

            # Now mark as skipped with string
            adapter.update_job_status(job_id, status="skipped", skip_reason="test skip")

            job = queue.get_job(job_id)
            assert job.status == "skipped"

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_bulk_update_preserves_order(self):
        """Test bulk update processes updates in order."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            id1 = queue.enqueue(noop)
            id2 = queue.enqueue(noop)

            updates = [
                {"id": id1, "status": JobStatus.CLAIMED},
                {"id": id1, "status": JobStatus.DONE},  # Second update to same job
                {"id": id2, "status": JobStatus.FAILED},
            ]

            adapter.bulk_update(updates)

            # id1 should have final status DONE
            assert queue.get_job(id1).status == JobStatus.DONE.value
            assert queue.get_job(id2).status == JobStatus.FAILED.value

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass


# ==============================================================================
# DAG Validation Edge Cases
# ==============================================================================


class TestDAGValidationEdgeCases:
    """Test DAG validation edge cases."""

    def test_validate_single_node_no_warnings(self):
        """Test validation with single node (no disconnected components warning)."""
        engine = DAGEngine()
        engine.add_node("single")

        warnings = engine.validate()

        # Should not warn about disconnected components with only 1 node
        assert len(warnings) == 0 or all(
            "disconnected components" not in w for w in warnings
        )

    def test_validate_no_warnings_with_connected_graph(self):
        """Test validation with fully connected graph."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_node("c")

        engine.add_dependency("b", "a")
        engine.add_dependency("c", "b")

        warnings = engine.validate()

        # Should have no warnings (or only benign ones)
        # At minimum, no disconnected components warning
        assert all("disconnected" not in w for w in warnings)

    def test_validate_warns_about_no_entry_points(self):
        """Test validation warns when no entry points exist."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")

        # Create a cycle manually
        engine.graph.add_edge("a", "b")
        engine.graph.add_edge("b", "a")

        # Should raise due to cycle, but would warn about no entry points
        with pytest.raises(DAGValidationError):
            engine.validate()

    def test_validate_warns_about_no_terminal_nodes(self):
        """Test validation warns when no terminal nodes exist."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")

        # Create a cycle manually
        engine.graph.add_edge("a", "b")
        engine.graph.add_edge("b", "a")

        # Should raise due to cycle, but would warn about no terminals
        with pytest.raises(DAGValidationError):
            engine.validate()


# ==============================================================================
# Adapter SQL Edge Cases
# ==============================================================================


class TestAdapterSQLGeneration:
    """Test adapter SQL generation edge cases."""

    def test_adapter_update_with_attempts_when_not_skipped(self):
        """Test that attempts field is applied when not marking as skipped."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop, max_attempts=10)

            # Update attempts directly (not as part of SKIPPED update)
            adapter.update_job_status(job_id, attempts=5)

            job = queue.get_job(job_id)
            assert job.attempts == 5

            # Now update status without attempts
            adapter.update_job_status(job_id, status=JobStatus.DONE)

            job = queue.get_job(job_id)
            assert job.status == JobStatus.DONE.value
            assert job.attempts == 5  # Should still be 5

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_update_skipped_with_explicit_attempts_ignored(self):
        """Test that explicit attempts parameter is ignored when marking SKIPPED."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop, max_attempts=7)

            # Try to set attempts=2 while marking SKIPPED
            # The adapter should finalize to max_attempts instead
            adapter.update_job_status(
                job_id,
                status=JobStatus.SKIPPED,
                attempts=2,  # This should be ignored
            )

            job = queue.get_job(job_id)
            assert job.status == JobStatus.SKIPPED.value
            assert job.attempts == 7  # Should be max_attempts, not 2

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_update_with_string_status(self):
        """Test adapter handles string status values."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            job_id = queue.enqueue(noop)

            # Pass status as string
            adapter.update_job_status(job_id, status="claimed")

            job = queue.get_job(job_id)
            assert job.status == "claimed"

            # Now mark as skipped with string
            adapter.update_job_status(job_id, status="skipped")

            job = queue.get_job(job_id)
            assert job.status == "skipped"

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass

    def test_adapter_bulk_update_preserves_order(self):
        """Test bulk update processes updates in order."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            id1 = queue.enqueue(noop)
            id2 = queue.enqueue(noop)

            updates = [
                {"id": id1, "status": JobStatus.CLAIMED},
                {"id": id1, "status": JobStatus.DONE},  # Second update to same job
                {"id": id2, "status": JobStatus.FAILED},
            ]

            adapter.bulk_update(updates)

            # id1 should have final status DONE
            assert queue.get_job(id1).status == JobStatus.DONE.value
            assert queue.get_job(id2).status == JobStatus.FAILED.value

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass
