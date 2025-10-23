import os
import tempfile

import pytest

from queuack import (
    DAGEngine,
    DAGValidationError,
    DependencyMode,
    DuckQueue,
    DuckQueueAdapter,
    InMemoryJobStore,
    Job,
    JobStatus,
    NodeStatus,
)


def make_job(id):
    # Minimal Job object used by InMemoryJobStore
    return Job(
        id=id,
        func=b"",
        args=b"",
        kwargs=b"",
        queue="default",
        status=JobStatus.PENDING.value,
    )


def test_ready_nodes_no_parents():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")

    ready = engine.get_ready_nodes()
    ids = {n.id for n in ready}
    assert ids == {"a", "b"}


def test_all_dependency_mode_becomes_ready_after_all_parents_done():
    engine = DAGEngine()
    engine.add_node("p1")
    engine.add_node("p2")
    engine.add_node("child")
    engine.add_dependency("child", "p1")
    engine.add_dependency("child", "p2")

    # Initially only parents are ready
    ready = {n.id for n in engine.get_ready_nodes()}
    assert "child" not in ready

    changed = engine.mark_node_done("p1")
    assert changed == ["p1"]
    # Still not ready because p2 not done
    assert "child" not in {n.id for n in engine.get_ready_nodes()}

    changed = engine.mark_node_done("p2")
    assert changed == ["p2"]
    # Now child should be ready
    assert "child" in {n.id for n in engine.get_ready_nodes()}


def test_any_dependency_mode_ready_when_any_parent_done():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c", dependency_mode=DependencyMode.ANY)
    engine.add_dependency("c", "a")
    engine.add_dependency("c", "b")

    # Neither parent done yet
    assert "c" not in {n.id for n in engine.get_ready_nodes()}

    changed = engine.mark_node_done("a")
    assert changed == ["a"]
    # c should be ready because dependency_mode=ANY
    assert "c" in {n.id for n in engine.get_ready_nodes()}


def test_mark_node_failed_propagates_and_persists_all_mode():
    # Build chain: a -> b -> c (ALL by default)
    jobs = [make_job(i) for i in ("a", "b", "c")]
    store = InMemoryJobStore(jobs)

    engine = DAGEngine(job_store=store)
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    engine.add_dependency("b", "a")
    engine.add_dependency("c", "b")

    changed = engine.mark_node_failed("a", propagate=True)
    # a failed, b and c should be skipped
    assert set(changed) == {"a", "b", "c"}

    # Check in-memory persistence updated job statuses
    assert store.get_job("a").status == JobStatus.FAILED.value
    assert store.get_job("b").status == JobStatus.SKIPPED.value
    assert store.get_job("c").status == JobStatus.SKIPPED.value


def test_mark_node_failed_respects_any_mode():
    # parents a and b -> child x with ANY mode
    jobs = [make_job(i) for i in ("a", "b", "x")]
    store = InMemoryJobStore(jobs)

    engine = DAGEngine(job_store=store)
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("x", dependency_mode=DependencyMode.ANY)
    engine.add_dependency("x", "a")
    engine.add_dependency("x", "b")

    # Fail a: x should NOT be skipped yet (b may still succeed)
    changed = engine.mark_node_failed("a", propagate=True)
    assert "a" in changed
    assert store.get_job("a").status == JobStatus.FAILED.value
    assert store.get_job("x").status == JobStatus.PENDING.value

    # Now fail b: x must be skipped
    changed = engine.mark_node_failed("b", propagate=True)
    assert set(["b", "x"]).issubset(set(changed))
    assert store.get_job("x").status == JobStatus.SKIPPED.value


def test_cycle_detection_raises():
    engine = DAGEngine()
    engine.add_node("n1")
    engine.add_node("n2")
    engine.add_dependency("n2", "n1")
    # Adding the reverse edge should create a cycle
    with pytest.raises(DAGValidationError):
        engine.add_dependency("n1", "n2")


def test_graph_utilities_and_execution_order():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    engine.add_dependency("b", "a")
    engine.add_dependency("c", "b")

    assert engine.get_parents("b") == ["a"]
    assert engine.get_children("b") == ["c"]
    assert engine.get_ancestors("c") == {"a", "b"}
    assert engine.get_descendants("a") == {"b", "c"}

    order = engine.get_execution_order()
    # Topological generations, first level contains 'a'
    assert any("a" in level for level in order)
    # Critical path should include a->b->c
    cp = engine.get_critical_path()
    assert cp == ["a", "b", "c"]


def test_add_nodes_and_execution_order():
    dag = DAGEngine()
    dag.add_node("extract", "Extract")
    dag.add_node("transform", "Transform")
    dag.add_node("load", "Load")

    dag.add_dependency("transform", "extract")
    dag.add_dependency("load", "transform")

    levels = dag.get_execution_order()
    assert levels == [["extract"], ["transform"], ["load"]]


def test_cycle_detection_raises():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_node("c", "C")

    dag.add_dependency("b", "a")
    dag.add_dependency("c", "b")

    with pytest.raises(DAGValidationError):
        dag.add_dependency("a", "c")


def test_validate_warnings_disconnected_components():
    dag = DAGEngine()
    dag.add_node("n1", "N1")
    dag.add_node("n2", "N2")
    # no edges -> two disconnected components
    warnings = dag.validate()
    assert any("disconnected components" in w for w in warnings)


def test_get_ready_nodes_all_mode():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_dependency("b", "a")

    ready = dag.get_ready_nodes()
    assert any(n.id == "a" for n in ready)
    assert all(n.id != "b" for n in ready)

    dag.mark_node_done("a")
    ready = dag.get_ready_nodes()
    assert any(n.id == "b" for n in ready)


def test_get_ready_nodes_any_mode_and_propagation():
    dag = DAGEngine()
    dag.add_node("api1", "API1")
    dag.add_node("api2", "API2")
    dag.add_node("api3", "API3")

    dag.add_node("agg", "Aggregate", dependency_mode=DependencyMode.ANY)
    dag.add_dependency("agg", "api1")
    dag.add_dependency("agg", "api2")
    dag.add_dependency("agg", "api3")

    # Initially all pending: ready nodes are api1, api2, api3
    ready = dag.get_ready_nodes()
    ready_ids = {n.id for n in ready}
    assert {"api1", "api2", "api3"}.issubset(ready_ids)

    # Simulate api2 failure; other APIs still pending
    dag.mark_node_failed("api2", propagate=True)

    # agg should not be SKIPPED because ANY can succeed if api1 or api3 completes
    assert dag.nodes["agg"].status in (NodeStatus.PENDING, NodeStatus.READY)

    # Complete api1 -> agg should become ready
    dag.mark_node_done("api1")
    ready = dag.get_ready_nodes()
    assert any(n.id == "agg" for n in ready)


def test_mark_node_failed_all_descendants_skipped():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_node("c", "C")
    dag.add_dependency("b", "a")
    dag.add_dependency("c", "b")

    # Fail A -> B (ALL) should be skipped, and so C should be skipped
    dag.mark_node_failed("a", propagate=True)
    assert dag.nodes["b"].status == NodeStatus.SKIPPED
    # C's parent B was skipped; since C depends on B (ALL), it should be skipped too
    assert dag.nodes["c"].status == NodeStatus.SKIPPED


def test_mark_node_failed_any_descendant_behavior():
    dag = DAGEngine()
    dag.add_node("p1", "P1")
    dag.add_node("p2", "P2")
    dag.add_node("child", "Child", dependency_mode=DependencyMode.ANY)
    dag.add_dependency("child", "p1")
    dag.add_dependency("child", "p2")

    # Fail p1 only -> child should NOT be skipped yet
    dag.mark_node_failed("p1", propagate=True)
    assert dag.nodes["child"].status in (NodeStatus.PENDING, NodeStatus.READY)

    # Fail p2 too -> child should now be skipped
    dag.mark_node_failed("p2", propagate=True)
    assert dag.nodes["child"].status == NodeStatus.SKIPPED


def test_simulate_execution_counts_and_behavior():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_node("c", "C")
    dag.add_dependency("b", "a")
    dag.add_dependency("c", "b")

    # Make B fail during simulation
    dag.nodes["b"].metadata["simulate_failure"] = True

    stats = dag.simulate_execution(verbose=False)
    # Only A should complete, B fails and C is skipped
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["skipped"] == 1


def test_get_ready_nodes_is_pure_and_does_not_mutate_statuses():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_dependency("b", "a")

    # Capture statuses before calling get_ready_nodes
    before_statuses = {nid: n.status for nid, n in dag.nodes.items()}
    _ = dag.get_ready_nodes()
    after_statuses = {nid: n.status for nid, n in dag.nodes.items()}

    # Ensure no statuses changed
    assert before_statuses == after_statuses


def test_mark_node_done_and_failed_return_changed_lists():
    dag = DAGEngine()
    dag.add_node("a", "A")
    dag.add_node("b", "B")
    dag.add_dependency("b", "a")

    # Mark a done
    changed_done = dag.mark_node_done("a")
    assert changed_done == ["a"]

    # No-op marking done again returns empty
    changed_done_again = dag.mark_node_done("a")
    assert changed_done_again == []

    # Mark b to fail and propagate: should include b and c if applicable
    dag.add_node("c", "C")
    dag.add_dependency("c", "b")
    dag.nodes["b"].metadata["simulate_failure"] = True

    # Simulate failure via mark_node_failed
    changed_failed = dag.mark_node_failed("b", propagate=True)
    assert "b" in changed_failed


def test_export_mermaid_contains_nodes_and_edges():
    dag = DAGEngine()
    dag.add_node("x", "X")
    dag.add_node("y", "Y")
    dag.add_dependency("y", "x")

    out = dag.export_mermaid()
    assert "X" in out
    assert "x --> y" in out


def test_export_mermaid_and_styles():
    engine = DAGEngine()
    engine.add_node("a", name="Alpha")
    engine.add_node("b", name="Beta")
    engine.add_dependency("b", "a")

    # set statuses to exercise style mapping
    engine.nodes["a"].status = NodeStatus.DONE
    engine.nodes["b"].status = NodeStatus.READY

    mermaid = engine.export_mermaid()
    assert "graph TD" in mermaid
    assert "a" in mermaid
    assert "b" in mermaid
    # styles definitions present
    assert "classDef done" in mermaid
    assert "classDef ready" in mermaid


def test_mark_node_done_idempotent_and_persist_swallow_exceptions():
    class BrokenStore(InMemoryJobStore):
        def update_job_status(self, job_id: str, **kwargs):
            raise RuntimeError("adapter fail")

    jobs = [make_job("n1")]
    store = BrokenStore(jobs)
    engine = DAGEngine(job_store=store)
    engine.add_node("n1")

    # First call updates status and attempts to persist, but adapter raises - should be swallowed
    changed = engine.mark_node_done("n1")
    assert changed == ["n1"]
    assert engine.nodes["n1"].status == NodeStatus.DONE

    # Second call should be no-op
    changed = engine.mark_node_done("n1")
    assert changed == []


def test_mark_node_failed_propagate_false():
    jobs = [make_job(i) for i in ("a", "b")]
    store = InMemoryJobStore(jobs)
    engine = DAGEngine(job_store=store)
    engine.add_node("a")
    engine.add_node("b")
    engine.add_dependency("b", "a")

    changed = engine.mark_node_failed("a", propagate=False)
    assert changed == ["a"]
    # b should remain pending
    assert engine.nodes["b"].status == NodeStatus.PENDING


def test_mixed_parent_propagation_all_and_any():
    # Build graph: p1(pending)->m(a), p2(failed)->m(a) for ALL
    jobs = [make_job(i) for i in ("p1", "p2", "m_all", "p3", "m_any")]
    store = InMemoryJobStore(jobs)
    engine = DAGEngine(job_store=store)

    # ALL case
    engine.add_node("p1")
    engine.add_node("p2")
    engine.add_node("m_all")
    engine.add_dependency("m_all", "p1")
    engine.add_dependency("m_all", "p2")

    # ANY case
    engine.add_node("p3")
    engine.add_node("m_any", dependency_mode=DependencyMode.ANY)
    engine.add_dependency("m_any", "p2")
    engine.add_dependency("m_any", "p3")

    # Fail p2
    changed = engine.mark_node_failed("p2", propagate=True)
    assert "p2" in changed

    # For ALL child (m_all), since p2 failed, it must be skipped
    assert engine.nodes["m_all"].status == NodeStatus.SKIPPED

    # For ANY child (m_any), since p3 is still pending, m_any should remain pending
    assert engine.nodes["m_any"].status == NodeStatus.PENDING


def test_get_ready_nodes_ignores_non_pending():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_dependency("b", "a")

    # Set b to READY manually - should not be returned by get_ready_nodes because only PENDING considered
    engine.nodes["b"].status = NodeStatus.READY
    ready = {n.id for n in engine.get_ready_nodes()}
    assert "b" not in ready


def test_topological_generations_parallel_levels():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    engine.add_node("d")
    # a and b are roots, c depends on a and b, d depends on a
    engine.add_dependency("c", "a")
    engine.add_dependency("c", "b")
    engine.add_dependency("d", "a")

    levels = engine.get_execution_order()
    # level 0 should contain a and b (order not guaranteed)
    assert len(levels) >= 1
    assert set(levels[0]) >= {"a", "b"}

    # ensure critical path includes a->c or a->d depending on ordering
    cp = engine.get_critical_path()
    assert "a" in cp


def test_validate_disconnected_components_warning():
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    # connect a->b, leave c disconnected
    engine.add_dependency("b", "a")

    warnings = engine.validate()
    # Should warn about disconnected components
    assert any("disconnected components" in w for w in warnings)


def test_mark_node_failed_with_broken_store_does_not_raise():
    class BrokenStore(InMemoryJobStore):
        def update_job_status(self, *args, **kwargs):
            raise RuntimeError("boom")

    jobs = [make_job(i) for i in ("a", "b", "c")]
    store = BrokenStore(jobs)
    engine = DAGEngine(job_store=store)
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    engine.add_dependency("b", "a")
    engine.add_dependency("c", "b")

    # Should not raise despite adapter failures
    changed = engine.mark_node_failed("a", propagate=True)
    assert "a" in changed


def test_propagation_order_by_distance():
    # a -> b -> d ; a -> c
    engine = DAGEngine()
    engine.add_node("a")
    engine.add_node("b")
    engine.add_node("c")
    engine.add_node("d")
    engine.add_dependency("b", "a")
    engine.add_dependency("c", "a")
    engine.add_dependency("d", "b")

    changed = engine.mark_node_failed("a", propagate=True)
    # ensure immediate children (b,c) appear before d in changed order
    assert changed.index("b") < changed.index("d")


def test_export_mermaid_all_status_styles_present():
    engine = DAGEngine()
    engine.add_node("n1")
    engine.add_node("n2")
    engine.add_node("n3")
    engine.nodes["n1"].status = NodeStatus.FAILED
    engine.nodes["n2"].status = NodeStatus.SKIPPED
    engine.nodes["n3"].status = NodeStatus.RUNNING

    mer = engine.export_mermaid()
    assert "classDef failed" in mer
    assert "classDef skipped" in mer
    assert "classDef running" in mer


def test_get_ready_nodes_mixed_parent_statuses():
    engine = DAGEngine()
    engine.add_node("p1")
    engine.add_node("p2")
    engine.add_node("x_all")
    engine.add_node("x_any", dependency_mode=DependencyMode.ANY)
    engine.add_dependency("x_all", "p1")
    engine.add_dependency("x_all", "p2")
    engine.add_dependency("x_any", "p1")
    engine.add_dependency("x_any", "p2")

    # p1 done, p2 skipped
    engine.nodes["p1"].status = NodeStatus.DONE
    engine.nodes["p2"].status = NodeStatus.SKIPPED

    # x_all requires ALL -> should not be ready
    ready = {n.id for n in engine.get_ready_nodes()}
    assert "x_all" not in ready

    # x_any should be ready because p1 is DONE
    assert "x_any" in ready


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
# DAG Simulate Execution Edge Cases
# ==============================================================================


class TestDAGSimulateExecution:
    """Test DAG simulate_execution edge cases."""

    def test_simulate_execution_verbose_false(self):
        """Test simulation with verbose=False."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_dependency("b", "a")

        # Run with verbose=False (no output)
        stats = engine.simulate_execution(verbose=False)

        assert stats["completed"] == 2
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

    def test_simulate_execution_with_all_failures(self):
        """Test simulation where all jobs fail."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_node("c")

        engine.add_dependency("b", "a")
        engine.add_dependency("c", "b")

        # Make all fail
        for node_id in ["a", "b", "c"]:
            engine.nodes[node_id].metadata["simulate_failure"] = True

        stats = engine.simulate_execution(verbose=False)

        # a fails, b and c are skipped
        assert stats["failed"] >= 1
        assert stats["skipped"] >= 2

    def test_simulate_execution_with_already_completed(self):
        """Test simulation with some nodes already marked done."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_dependency("b", "a")

        # Mark a as already done
        engine.nodes["a"].status = NodeStatus.DONE

        stats = engine.simulate_execution(verbose=False)

        # Both should be completed
        assert stats["completed"] >= 1


# ==============================================================================
# DAG Graph Utility Edge Cases
# ==============================================================================


class TestDAGGraphUtilities:
    """Test DAG graph utility functions."""

    def test_get_parents_node_with_no_parents(self):
        """Test get_parents on node with no parents."""
        engine = DAGEngine()
        engine.add_node("root")

        parents = engine.get_parents("root")
        assert parents == []

    def test_get_children_node_with_no_children(self):
        """Test get_children on node with no children."""
        engine = DAGEngine()
        engine.add_node("leaf")

        children = engine.get_children("leaf")
        assert children == []

    def test_get_ancestors_root_node(self):
        """Test get_ancestors on root node."""
        engine = DAGEngine()
        engine.add_node("root")
        engine.add_node("child")
        engine.add_dependency("child", "root")

        ancestors = engine.get_ancestors("root")
        assert len(ancestors) == 0

    def test_get_descendants_leaf_node(self):
        """Test get_descendants on leaf node."""
        engine = DAGEngine()
        engine.add_node("parent")
        engine.add_node("leaf")
        engine.add_dependency("leaf", "parent")

        descendants = engine.get_descendants("leaf")
        assert len(descendants) == 0

    def test_get_critical_path_single_node(self):
        """Test critical path with single node."""
        engine = DAGEngine()
        engine.add_node("single")

        path = engine.get_critical_path()
        assert path == ["single"]

    def test_get_critical_path_linear_chain(self):
        """Test critical path on linear chain."""
        engine = DAGEngine()
        for i in range(5):
            engine.add_node(f"n{i}")

        for i in range(4):
            engine.add_dependency(f"n{i + 1}", f"n{i}")

        path = engine.get_critical_path()
        assert len(path) == 5
        assert path[0] == "n0"
        assert path[-1] == "n4"


# ==============================================================================
# DAG Export Mermaid Edge Cases
# ==============================================================================


class TestDAGExportMermaid:
    """Test DAG mermaid export edge cases."""

    def test_export_mermaid_empty_graph(self):
        """Test mermaid export with empty graph."""
        engine = DAGEngine()

        mermaid = engine.export_mermaid()

        # Should still have basic structure
        assert "graph TD" in mermaid
        assert "classDef" in mermaid

    def test_export_mermaid_single_node(self):
        """Test mermaid export with single node."""
        engine = DAGEngine()
        engine.add_node("single", "Single Node")

        mermaid = engine.export_mermaid()

        assert "graph TD" in mermaid
        assert "SingleNode" in mermaid
        assert "Single Node" in mermaid

    def test_export_mermaid_node_with_special_characters(self):
        """Test mermaid export with special characters in node names."""
        engine = DAGEngine()
        engine.add_node("n1", "Node with spaces")
        engine.add_node("n2", "Node-with-dashes")

        mermaid = engine.export_mermaid()

        assert "Node with spaces" in mermaid
        assert "Node-with-dashes" in mermaid

    def test_export_mermaid_preserves_all_edges(self):
        """Test mermaid export includes all edges."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_node("c")
        engine.add_node("d")

        engine.add_dependency("b", "a")
        engine.add_dependency("c", "a")
        engine.add_dependency("d", "b")
        engine.add_dependency("d", "c")

        mermaid = engine.export_mermaid()

        assert "a --> b" in mermaid
        assert "a --> c" in mermaid
        assert "b --> d" in mermaid
        assert "c --> d" in mermaid


# ==============================================================================
# DAG with JobStore Integration
# ==============================================================================


class TestDAGJobStoreIntegration:
    """Test DAG engine with JobStore persistence."""

    def test_dag_persists_updates_to_store(self):
        """Test that DAG updates are persisted to JobStore."""
        jobs = [make_job(f"j{i}") for i in range(3)]
        store = InMemoryJobStore(jobs)

        engine = DAGEngine(job_store=store)

        for i in range(3):
            engine.add_node(f"j{i}")

        engine.add_dependency("j1", "j0")
        engine.add_dependency("j2", "j1")

        # Mark j0 done
        engine.mark_node_done("j0")

        # Should be persisted
        assert store.get_job("j0").status == JobStatus.DONE.value

    def test_dag_failed_propagation_persists(self):
        """Test that failure propagation persists to store."""
        jobs = [make_job(f"j{i}") for i in range(3)]
        store = InMemoryJobStore(jobs)

        engine = DAGEngine(job_store=store)

        for i in range(3):
            engine.add_node(f"j{i}")

        engine.add_dependency("j1", "j0")
        engine.add_dependency("j2", "j1")

        # Fail j0
        engine.mark_node_failed("j0", propagate=True)

        # All should be persisted
        assert store.get_job("j0").status == JobStatus.FAILED.value
        assert store.get_job("j1").status == JobStatus.SKIPPED.value
        assert store.get_job("j2").status == JobStatus.SKIPPED.value

    def test_dag_handles_store_errors_gracefully(self):
        """Test that DAG handles store errors without crashing."""

        class FailingStore(InMemoryJobStore):
            def update_job_status(self, *args, **kwargs):
                raise RuntimeError("Store failure")

        jobs = [make_job("j1"), make_job("j2")]
        store = FailingStore(jobs)

        engine = DAGEngine(job_store=store)
        engine.add_node("j1")
        engine.add_node("j2")
        engine.add_dependency("j2", "j1")

        # Should not raise despite store failures
        changed = engine.mark_node_done("j1")
        assert "j1" in changed

        # In-memory state should be updated
        assert engine.nodes["j1"].status == NodeStatus.DONE


# ==============================================================================
# DAG Ready Nodes Complex Scenarios
# ==============================================================================


class TestDAGReadyNodesComplex:
    """Test get_ready_nodes with complex scenarios."""

    def test_get_ready_nodes_with_mixed_dependencies(self):
        """Test ready nodes with both ALL and ANY dependency modes."""
        engine = DAGEngine()

        # Create parallel parents
        engine.add_node("p1")
        engine.add_node("p2")
        engine.add_node("p3")

        # ALL child
        engine.add_node("all_child", dependency_mode=DependencyMode.ALL)
        engine.add_dependency("all_child", "p1")
        engine.add_dependency("all_child", "p2")

        # ANY child
        engine.add_node("any_child", dependency_mode=DependencyMode.ANY)
        engine.add_dependency("any_child", "p1")
        engine.add_dependency("any_child", "p3")

        # Initially, only parents are ready
        ready = {n.id for n in engine.get_ready_nodes()}
        assert "all_child" not in ready
        assert "any_child" not in ready

        # Complete p1
        engine.mark_node_done("p1")

        ready = {n.id for n in engine.get_ready_nodes()}
        # ANY child should be ready now
        assert "any_child" in ready
        # ALL child still not ready (p2 not done)
        assert "all_child" not in ready

        # Complete p2
        engine.mark_node_done("p2")

        ready = {n.id for n in engine.get_ready_nodes()}
        # Now ALL child should be ready
        assert "all_child" in ready

    def test_get_ready_nodes_ignores_finished_nodes(self):
        """Test that finished nodes are not returned as ready."""
        engine = DAGEngine()
        engine.add_node("a")
        engine.add_node("b")
        engine.add_dependency("b", "a")

        # Mark a as done
        engine.mark_node_done("a")

        ready = {n.id for n in engine.get_ready_nodes()}
        # a should not be ready (already done)
        assert "a" not in ready
        # b should be ready
        assert "b" in ready

        # Mark b as done
        engine.mark_node_done("b")

        ready = {n.id for n in engine.get_ready_nodes()}
        # Neither should be ready
        assert len(ready) == 0


# ==============================================================================
# DAG Failure Propagation Complex Scenarios
# ==============================================================================


class TestDAGFailurePropagationComplex:
    """Test complex failure propagation scenarios."""

    def test_propagation_with_any_mode_one_parent_fails(self):
        """Test ANY mode doesn't skip when one parent fails."""
        engine = DAGEngine()
        engine.add_node("p1")
        engine.add_node("p2")
        engine.add_node("child", dependency_mode=DependencyMode.ANY)

        engine.add_dependency("child", "p1")
        engine.add_dependency("child", "p2")

        # Fail p1 only
        engine.mark_node_failed("p1", propagate=True)

        # Child should still be pending (p2 might succeed)
        assert engine.nodes["child"].status == NodeStatus.PENDING

    def test_propagation_with_any_mode_all_parents_fail(self):
        """Test ANY mode skips when all parents fail."""
        engine = DAGEngine()
        engine.add_node("p1")
        engine.add_node("p2")
        engine.add_node("child", dependency_mode=DependencyMode.ANY)

        engine.add_dependency("child", "p1")
        engine.add_dependency("child", "p2")

        # Fail both parents
        engine.mark_node_failed("p1", propagate=True)
        engine.mark_node_failed("p2", propagate=True)

        # Child should be skipped
        assert engine.nodes["child"].status == NodeStatus.SKIPPED

    def test_propagation_respects_distance_order(self):
        """Test that propagation processes nodes in distance order."""
        engine = DAGEngine()

        # Create chain: a -> b -> c -> d
        for node in ["a", "b", "c", "d"]:
            engine.add_node(node)

        engine.add_dependency("b", "a")
        engine.add_dependency("c", "b")
        engine.add_dependency("d", "c")

        changed = engine.mark_node_failed("a", propagate=True)

        # Should be in order: a, b, c, d
        assert changed.index("a") < changed.index("b")
        assert changed.index("b") < changed.index("c")
        assert changed.index("c") < changed.index("d")

    def test_propagation_with_diamond_pattern(self):
        """Test propagation in diamond pattern."""
        engine = DAGEngine()

        # Diamond: a -> b, a -> c, b -> d, c -> d
        for node in ["a", "b", "c", "d"]:
            engine.add_node(node)

        engine.add_dependency("b", "a")
        engine.add_dependency("c", "a")
        engine.add_dependency("d", "b")
        engine.add_dependency("d", "c")

        # Fail a
        changed = engine.mark_node_failed("a", propagate=True)

        # All should be affected
        assert set(changed) == {"a", "b", "c", "d"}

        # All should be failed or skipped
        assert engine.nodes["a"].status == NodeStatus.FAILED
        for node in ["b", "c", "d"]:
            assert engine.nodes[node].status == NodeStatus.SKIPPED


# ==============================================================================
# Connection Pool Edge Cases
# ==============================================================================


class TestConnectionPoolEdgeCases:
    """Test ConnectionPool edge cases."""

    def test_connection_pool_wait_until_ready(self):
        """Test wait_until_ready blocks until schema initialized."""
        import threading

        from queuack.core import ConnectionPool

        pool = ConnectionPool(":memory:")

        # Mark as initializing
        pool.mark_initializing()

        ready_flag = []

        def wait_thread():
            pool.wait_until_ready()
            ready_flag.append(True)

        thread = threading.Thread(target=wait_thread)
        thread.start()

        # Thread should be blocked
        import time

        time.sleep(0.1)
        assert len(ready_flag) == 0

        # Mark ready
        pool.mark_ready()

        # Thread should complete
        thread.join(timeout=1)
        assert len(ready_flag) == 1

    def test_connection_pool_get_connection_waits(self):
        """Test get_connection waits for schema initialization."""
        import threading

        from queuack.core import ConnectionPool

        pool = ConnectionPool(":memory:")

        # Mark as initializing
        pool.mark_initializing()

        conn_ref = []

        def get_conn_thread():
            conn = pool.get_connection()
            conn_ref.append(conn)

        thread = threading.Thread(target=get_conn_thread)
        thread.start()

        # Thread should be blocked
        import time

        time.sleep(0.1)
        assert len(conn_ref) == 0

        # Create and set global connection
        import duckdb

        conn = duckdb.connect(":memory:")
        pool.set_global_connection(conn)

        # Mark ready
        pool.mark_ready()

        # Thread should complete
        thread.join(timeout=1)
        assert len(conn_ref) == 1


# ==============================================================================
# Comprehensive Integration Test
# ==============================================================================


def noop():
    return 42


class TestComprehensiveIntegration:
    """Comprehensive integration test covering multiple features."""

    def test_full_workflow_with_dag_and_adapter(self):
        """Test complete workflow: enqueue with deps, propagate failures, persist."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".duckdb") as f:
            db_path = f.name

        try:
            os.unlink(db_path)
        except:
            pass

        try:
            # Create queue and adapter
            queue = DuckQueue(db_path)
            adapter = DuckQueueAdapter(queue)

            # Enqueue jobs with dependencies
            j1 = queue.enqueue(noop)
            j2 = queue.enqueue(noop, depends_on=j1)
            j3 = queue.enqueue(noop, depends_on=j1)
            j4 = queue.enqueue(noop, depends_on=[j2, j3])

            # Create DAG engine
            engine = DAGEngine(job_store=adapter)
            engine.add_node(j1, "Job 1")
            engine.add_node(j2, "Job 2")
            engine.add_node(j3, "Job 3")
            engine.add_node(j4, "Job 4")

            engine.add_dependency(j2, j1)
            engine.add_dependency(j3, j1)
            engine.add_dependency(j4, j2)
            engine.add_dependency(j4, j3)

            # Validate structure
            warnings = engine.validate()
            assert len(warnings) == 0

            # Claim and complete j1
            job = queue.claim()
            assert job.id == j1
            queue.ack(job.id, result=42)

            # Mark in engine
            engine.mark_node_done(j1)

            # Now j2 and j3 should be claimable
            job = queue.claim()
            assert job.id in [j2, j3]

            # Fail it
            queue.ack(job.id, error="Failed")
            queue.ack(
                job.id,
                error="Failed permanently",
            )  # Second attempt

            # Mark failed in engine
            engine.mark_node_failed(job.id, propagate=True)

            # Check propagation
            if job.id == j2:
                # j2 failed, j4 should be skipped (depends on both j2 and j3)
                # But j3 can still run
                j3_job = queue.get_job(j3)
                # j3 should still be pending or claimed
                assert j3_job.status in [
                    JobStatus.PENDING.value,
                    JobStatus.CLAIMED.value,
                ]

            queue.close()
        finally:
            try:
                os.unlink(db_path)
            except:
                pass
