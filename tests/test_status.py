"""Tests for status.py - status mapping helpers."""

import pytest

from queuack import (
    JobStatus,
    NodeStatus,
    job_status_to_node_status,
    node_status_to_job_status,
)


class TestJobStatusToNodeStatus:
    """Test job_status_to_node_status mapping."""

    def test_pending_maps_to_pending(self):
        """Test PENDING JobStatus maps to PENDING NodeStatus."""
        assert job_status_to_node_status(JobStatus.PENDING) == NodeStatus.PENDING

    def test_delayed_maps_to_pending(self):
        """Test DELAYED JobStatus maps to PENDING NodeStatus."""
        assert job_status_to_node_status(JobStatus.DELAYED) == NodeStatus.PENDING

    def test_claimed_not_started_maps_to_pending(self):
        """Test CLAIMED (not started) maps to PENDING."""
        result = job_status_to_node_status(JobStatus.CLAIMED, claimed_started=False)
        assert result == NodeStatus.PENDING

    def test_claimed_started_maps_to_running(self):
        """Test CLAIMED (started) maps to RUNNING."""
        result = job_status_to_node_status(JobStatus.CLAIMED, claimed_started=True)
        assert result == NodeStatus.RUNNING

    def test_done_maps_to_done(self):
        """Test DONE JobStatus maps to DONE NodeStatus."""
        assert job_status_to_node_status(JobStatus.DONE) == NodeStatus.DONE

    def test_failed_maps_to_failed(self):
        """Test FAILED JobStatus maps to FAILED NodeStatus."""
        assert job_status_to_node_status(JobStatus.FAILED) == NodeStatus.FAILED

    def test_skipped_maps_to_skipped(self):
        """Test SKIPPED JobStatus maps to SKIPPED NodeStatus."""
        assert job_status_to_node_status(JobStatus.SKIPPED) == NodeStatus.SKIPPED

    def test_invalid_status_raises(self):
        """Test invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported JobStatus"):
            job_status_to_node_status("invalid_status")

    def test_claimed_default_not_started(self):
        """Test CLAIMED defaults to not started (PENDING)."""
        # When claimed_started not specified, should default to False
        result = job_status_to_node_status(JobStatus.CLAIMED)
        assert result == NodeStatus.PENDING


class TestNodeStatusToJobStatus:
    """Test node_status_to_job_status mapping."""

    def test_pending_maps_to_pending(self):
        """Test PENDING NodeStatus maps to PENDING JobStatus."""
        assert node_status_to_job_status(NodeStatus.PENDING) == JobStatus.PENDING

    def test_ready_maps_to_pending(self):
        """Test READY NodeStatus maps to PENDING JobStatus."""
        assert node_status_to_job_status(NodeStatus.READY) == JobStatus.PENDING

    def test_running_maps_to_claimed(self):
        """Test RUNNING NodeStatus maps to CLAIMED JobStatus."""
        assert node_status_to_job_status(NodeStatus.RUNNING) == JobStatus.CLAIMED

    def test_done_maps_to_done(self):
        """Test DONE NodeStatus maps to DONE JobStatus."""
        assert node_status_to_job_status(NodeStatus.DONE) == JobStatus.DONE

    def test_failed_maps_to_failed(self):
        """Test FAILED NodeStatus maps to FAILED JobStatus."""
        assert node_status_to_job_status(NodeStatus.FAILED) == JobStatus.FAILED

    def test_skipped_maps_to_skipped(self):
        """Test SKIPPED NodeStatus maps to SKIPPED JobStatus."""
        result = node_status_to_job_status(NodeStatus.SKIPPED)
        assert result == JobStatus.SKIPPED

    def test_skipped_with_flag_true(self):
        """Test SKIPPED with map_skipped_to_failed=True."""
        result = node_status_to_job_status(
            NodeStatus.SKIPPED, map_skipped_to_failed=True
        )
        # Even with flag, should map to SKIPPED (the flag is documented but not used)
        assert result == JobStatus.SKIPPED

    def test_skipped_with_flag_false(self):
        """Test SKIPPED with map_skipped_to_failed=False."""
        result = node_status_to_job_status(
            NodeStatus.SKIPPED, map_skipped_to_failed=False
        )
        assert result == JobStatus.SKIPPED

    def test_invalid_status_raises(self):
        """Test invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported NodeStatus"):
            node_status_to_job_status("invalid_status")


class TestRoundTripConversions:
    """Test round-trip conversions between statuses."""

    def test_pending_round_trip(self):
        """Test PENDING round-trips correctly."""
        job_status = JobStatus.PENDING
        node_status = job_status_to_node_status(job_status)
        back_to_job = node_status_to_job_status(node_status)

        assert back_to_job == JobStatus.PENDING

    def test_done_round_trip(self):
        """Test DONE round-trips correctly."""
        job_status = JobStatus.DONE
        node_status = job_status_to_node_status(job_status)
        back_to_job = node_status_to_job_status(node_status)

        assert back_to_job == JobStatus.DONE

    def test_failed_round_trip(self):
        """Test FAILED round-trips correctly."""
        job_status = JobStatus.FAILED
        node_status = job_status_to_node_status(job_status)
        back_to_job = node_status_to_job_status(node_status)

        assert back_to_job == JobStatus.FAILED

    def test_claimed_running_round_trip(self):
        """Test CLAIMED (running) round-trips correctly."""
        job_status = JobStatus.CLAIMED
        node_status = job_status_to_node_status(job_status, claimed_started=True)
        back_to_job = node_status_to_job_status(node_status)

        assert back_to_job == JobStatus.CLAIMED

    def test_delayed_maps_to_pending_not_reversible(self):
        """Test DELAYED -> PENDING doesn't reverse to DELAYED."""
        job_status = JobStatus.DELAYED
        node_status = job_status_to_node_status(job_status)
        back_to_job = node_status_to_job_status(node_status)

        # Can't distinguish DELAYED from PENDING when mapping back
        assert back_to_job == JobStatus.PENDING

    def test_ready_not_directly_from_job_status(self):
        """Test READY NodeStatus doesn't come from JobStatus."""
        # READY is a DAG-only state
        node_status = NodeStatus.READY
        job_status = node_status_to_job_status(node_status)

        assert job_status == JobStatus.PENDING


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_all_job_statuses_handled(self):
        """Test all JobStatus values can be converted."""
        for status in JobStatus:
            # Should not raise
            result = job_status_to_node_status(status)
            assert isinstance(result, NodeStatus)

    def test_all_node_statuses_handled(self):
        """Test all NodeStatus values can be converted."""
        for status in NodeStatus:
            # Should not raise
            result = node_status_to_job_status(status)
            assert isinstance(result, JobStatus)

    def test_claimed_started_parameter_only_affects_claimed(self):
        """Test claimed_started only affects CLAIMED status."""
        for status in [
            JobStatus.PENDING,
            JobStatus.DONE,
            JobStatus.FAILED,
            JobStatus.DELAYED,
        ]:
            result_false = job_status_to_node_status(status, claimed_started=False)
            result_true = job_status_to_node_status(status, claimed_started=True)

            # Should be the same regardless of claimed_started
            assert result_false == result_true

    def test_map_skipped_to_failed_parameter_documented(self):
        """Test map_skipped_to_failed parameter exists and is documented."""
        # The parameter is documented but currently doesn't change behavior
        # since we now have JobStatus.SKIPPED
        result_default = node_status_to_job_status(NodeStatus.SKIPPED)
        result_true = node_status_to_job_status(
            NodeStatus.SKIPPED, map_skipped_to_failed=True
        )
        result_false = node_status_to_job_status(
            NodeStatus.SKIPPED, map_skipped_to_failed=False
        )

        # All should map to SKIPPED
        assert result_default == JobStatus.SKIPPED
        assert result_true == JobStatus.SKIPPED
        assert result_false == JobStatus.SKIPPED
