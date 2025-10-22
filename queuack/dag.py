"""
Independent DAG resolution prototype for Queuack.

This module provides graph algorithms for dependency resolution WITHOUT
touching the queue implementation. Use this to validate the design before
integrating into queuack.py.

We'll leverage NetworkX for battle-tested graph algorithms rather than
reimplementing everything from scratch.
"""

from typing import Dict, List, Set, Any, Optional

import networkx as nx

from .job_store import JobStore
from .status import NodeStatus, DependencyMode
from .data_models import DAGNode
from .exceptions import DAGValidationError


class DAGEngine:
    """
    Core engine for DAG resolution using NetworkX.
    
    This handles:
    - Cycle detection
    - Topological sorting
    - Determining which nodes are ready to run
    - Failure propagation
    - Partial execution
    """
    
    def __init__(self, job_store: Optional[JobStore] = None):
        self.graph = nx.DiGraph()  # Directed graph
        self.nodes: Dict[str, DAGNode] = {}
        # Optional persistence adapter implementing JobStore
        self.job_store = job_store
    
    def add_node(
        self, 
        node_id: str, 
        name: str = None,
        dependency_mode: DependencyMode = DependencyMode.ALL,
        metadata: Dict[str, Any] = None
    ) -> DAGNode:
        """Add a node to the DAG."""
        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists")
        
        node = DAGNode(
            id=node_id,
            name=name or node_id,
            dependency_mode=dependency_mode,
            metadata=metadata or {}
        )
        
        self.nodes[node_id] = node
        self.graph.add_node(node_id)
        
        return node
    
    def add_dependency(self, child_id: str, parent_id: str):
        """
        Add edge: parent -> child (child depends on parent).
        
        Raises:
            ValueError: If nodes don't exist or would create cycle
        """
        if child_id not in self.nodes:
            raise ValueError(f"Child node {child_id} does not exist")
        if parent_id not in self.nodes:
            raise ValueError(f"Parent node {parent_id} does not exist")
        
        # Add edge
        self.graph.add_edge(parent_id, child_id)
        
        # Check for cycles IMMEDIATELY
        if not nx.is_directed_acyclic_graph(self.graph):
            # Rollback the edge
            self.graph.remove_edge(parent_id, child_id)
            
            # Find the cycle for better error message
            try:
                cycle = nx.find_cycle(self.graph)
                cycle_str = " -> ".join([str(n) for n, _ in cycle])
                raise DAGValidationError(
                    f"Adding dependency {parent_id} -> {child_id} creates cycle: {cycle_str}"
                )
            except nx.NetworkXNoCycle:
                # Shouldn't happen, but fallback
                raise DAGValidationError(
                    f"Adding dependency {parent_id} -> {child_id} creates a cycle"
                )
    
    def validate(self) -> List[str]:
        """
        Validate the DAG structure.
        
        Returns:
            List of warning messages (empty if valid)
        
        Raises:
            DAGValidationError: If DAG is invalid
        """
        warnings = []
        
        # Check it's a DAG (no cycles)
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            cycle_strs = [" -> ".join(cycle) for cycle in cycles]
            raise DAGValidationError(f"DAG contains cycles: {cycle_strs}")
        
        # Check for orphaned nodes (no path to/from other nodes)
        if len(self.graph.nodes) > 1:
            weakly_connected = list(nx.weakly_connected_components(self.graph))
            if len(weakly_connected) > 1:
                warnings.append(
                    f"DAG has {len(weakly_connected)} disconnected components. "
                    "This may be intentional (parallel workflows)."
                )
        
        # Check for nodes with no parents (entry points)
        entry_nodes = [n for n in self.graph.nodes if self.graph.in_degree(n) == 0]
        if not entry_nodes:
            warnings.append("DAG has no entry points (all nodes have dependencies)")
        
        # Check for nodes with no children (terminal nodes)
        terminal_nodes = [n for n in self.graph.nodes if self.graph.out_degree(n) == 0]
        if not terminal_nodes:
            warnings.append("DAG has no terminal nodes (no final outputs)")
        
        return warnings
    
    def get_ready_nodes(self) -> List[DAGNode]:
        """
        Get all nodes that are ready to execute.
        
        A node is ready if:
        - Status is PENDING
        - ALL parent dependencies are met (based on dependency_mode)
        """
        ready = []
        
        for node_id, node in self.nodes.items():
            if node.status != NodeStatus.PENDING:
                continue
            
            # Get parent statuses
            parents = list(self.graph.predecessors(node_id))
            
            if not parents:
                # No dependencies, ready to run
                ready.append(node)
                continue
            
            parent_statuses = [self.nodes[p].status for p in parents]
            
            # Check dependency mode
            if node.dependency_mode == DependencyMode.ALL:
                # All parents must be DONE
                if all(s == NodeStatus.DONE for s in parent_statuses):
                    ready.append(node)
            
            elif node.dependency_mode == DependencyMode.ANY:
                # At least one parent must be DONE
                if any(s == NodeStatus.DONE for s in parent_statuses):
                    ready.append(node)
        
        return ready
    
    def mark_node_done(self, node_id: str):
        """Mark a node as successfully completed."""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")
        changed: List[str] = []

        # Only update if there's an actual change
        if self.nodes[node_id].status != NodeStatus.DONE:
            self.nodes[node_id].status = NodeStatus.DONE
            changed.append(node_id)

            # Persist change if adapter provided
            if self.job_store is not None:
                try:
                    # Map NodeStatus to JobStatus and persist
                    from queuack.status import node_status_to_job_status
                    job_status = node_status_to_job_status(NodeStatus.DONE)
                    self.job_store.update_job_status(node_id, status=job_status)
                except Exception:
                    # Adapter failures should not break in-memory engine
                    pass

        return changed
    
    def mark_node_failed(self, node_id: str, propagate: bool = True):
        """
        Mark a node as failed.
        
        Args:
            node_id: Node that failed
            propagate: If True, mark descendants as SKIPPED
        """
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")
        
        changed: List[str] = []

        if self.nodes[node_id].status != NodeStatus.FAILED:
            self.nodes[node_id].status = NodeStatus.FAILED
            changed.append(node_id)

            if self.job_store is not None:
                try:
                    from queuack.status import node_status_to_job_status
                    job_status = node_status_to_job_status(NodeStatus.FAILED)
                    self.job_store.update_job_status(node_id, status=job_status)
                except Exception:
                    pass

        if propagate:
            # Propagate failure to descendants, but only mark a descendant SKIPPED
            # when, given its dependency_mode and current parent statuses,
            # it can no longer possibly become ready. This preserves semantics
            # for DependencyMode.ANY where other parents may still succeed.
            # Compute descendants and process them in increasing distance from the failed node
            # so that immediate children are marked before their own children.
            descendants = nx.descendants(self.graph, node_id)
            if descendants:
                distances = nx.single_source_shortest_path_length(self.graph, node_id)
                # Filter to the descendants set and sort by distance (ascending)
                sorted_desc = sorted(
                    [n for n in distances.keys() if n in descendants],
                    key=lambda n: distances[n]
                )
            else:
                sorted_desc = []

            for desc_id in sorted_desc:
                desc_node = self.nodes[desc_id]
                # Only consider nodes that haven't finished/failed/skipped yet
                if desc_node.status not in [NodeStatus.PENDING, NodeStatus.READY]:
                    continue

                parents = list(self.graph.predecessors(desc_id))
                parent_statuses = [self.nodes[p].status for p in parents]

                to_skip = False
                if desc_node.dependency_mode == DependencyMode.ALL:
                    # For ALL, any parent failure or skip makes this node unsatisfiable
                    if any(s in [NodeStatus.FAILED, NodeStatus.SKIPPED] for s in parent_statuses):
                        to_skip = True

                elif desc_node.dependency_mode == DependencyMode.ANY:
                    # For ANY, only skip if all parents are FAILED or SKIPPED
                    if all(s in [NodeStatus.FAILED, NodeStatus.SKIPPED] for s in parent_statuses):
                        to_skip = True

                if to_skip:
                    desc_node.status = NodeStatus.SKIPPED
                    changed.append(desc_id)
                    if self.job_store is not None:
                        try:
                            from queuack.status import node_status_to_job_status
                            job_status = node_status_to_job_status(NodeStatus.SKIPPED)
                            self.job_store.update_job_status(
                                desc_id,
                                status=job_status,
                                skipped_at=None,
                                skip_reason=f"propagated from {node_id}",
                                skipped_by="dag-engine",
                            )
                        except Exception:
                            pass
        return changed
    def get_execution_order(self) -> List[List[str]]:
        """
        Get nodes in execution order (topological sort with levels).
        
        Returns:
            List of levels, where each level contains node IDs that can run in parallel
        
        Example:
            [[A, B], [C], [D, E]]
            Level 0: A and B can run in parallel
            Level 1: C runs after A and B complete
            Level 2: D and E run in parallel after C
        """
        if not nx.is_directed_acyclic_graph(self.graph):
            raise DAGValidationError("Cannot get execution order for graph with cycles")
        
        # Use NetworkX's built-in topological generations
        levels = list(nx.topological_generations(self.graph))
        
        return levels
    
    def get_parents(self, node_id: str) -> List[str]:
        """Get immediate parent node IDs."""
        return list(self.graph.predecessors(node_id))
    
    def get_children(self, node_id: str) -> List[str]:
        """Get immediate child node IDs."""
        return list(self.graph.successors(node_id))
    
    def get_ancestors(self, node_id: str) -> Set[str]:
        """Get all ancestor node IDs (transitive parents)."""
        return nx.ancestors(self.graph, node_id)
    
    def get_descendants(self, node_id: str) -> Set[str]:
        """Get all descendant node IDs (transitive children)."""
        return nx.descendants(self.graph, node_id)
    
    def get_critical_path(self) -> List[str]:
        """
        Get the longest path through the DAG (critical path).
        
        This is useful for estimating total execution time.
        """
        return nx.dag_longest_path(self.graph)
    
    def export_mermaid(self) -> str:
        """
        Export DAG to Mermaid diagram format.
        
        Returns:
            Mermaid markdown string
        """
        lines = ["graph TD"]
        
        # Add nodes with styling based on status
        for node_id, node in self.nodes.items():
            label = node.name
            style = ""
            
            if node.status == NodeStatus.DONE:
                style = ":::done"
            elif node.status == NodeStatus.FAILED:
                style = ":::failed"
            elif node.status == NodeStatus.SKIPPED:
                style = ":::skipped"
            elif node.status == NodeStatus.RUNNING:
                style = ":::running"
            elif node.status == NodeStatus.READY:
                style = ":::ready"
            
            lines.append(f"    {node_id}[\"{label}\"]{style}")
        
        # Add edges
        for parent, child in self.graph.edges:
            lines.append(f"    {parent} --> {child}")
        
        # Add style definitions
        lines.extend([
            "",
            "    classDef done fill:#90EE90",
            "    classDef failed fill:#FFB6C6",
            "    classDef skipped fill:#D3D3D3",
            "    classDef running fill:#87CEEB",
            "    classDef ready fill:#FFD700"
        ])
        
        return "\n".join(lines)
    
    def simulate_execution(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Simulate DAG execution (for testing).
        
        Returns:
            Execution statistics
        """
        stats = {
            'total_nodes': len(self.nodes),
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'execution_levels': []
        }
        
        levels = self.get_execution_order()
        
        for level_num, level_nodes in enumerate(levels):
            if verbose:
                print(f"\n=== Level {level_num} ===")
            
            level_stats = {'level': level_num, 'nodes': []}
            
            for node_id in level_nodes:
                node = self.nodes[node_id]
                
                if node.status == NodeStatus.SKIPPED:
                    if verbose:
                        print(f"  SKIP: {node.name} (parent failed)")
                    stats['skipped'] += 1
                    level_stats['nodes'].append({'id': node_id, 'status': 'skipped'})
                    continue
                
                # Check if ready
                ready_nodes = self.get_ready_nodes()
                if node not in ready_nodes:
                    if verbose:
                        print(f"  WAIT: {node.name} (dependencies not met)")
                    continue
                
                # Simulate execution (mark as done or failed based on metadata)
                should_fail = node.metadata.get('simulate_failure', False)
                
                if should_fail:
                    if verbose:
                        print(f"  FAIL: {node.name}")
                    self.mark_node_failed(node_id, propagate=True)
                    stats['failed'] += 1
                    level_stats['nodes'].append({'id': node_id, 'status': 'failed'})
                else:
                    if verbose:
                        print(f"  DONE: {node.name}")
                    self.mark_node_done(node_id)
                    stats['completed'] += 1
                    level_stats['nodes'].append({'id': node_id, 'status': 'done'})
            
            stats['execution_levels'].append(level_stats)
        
        return stats


