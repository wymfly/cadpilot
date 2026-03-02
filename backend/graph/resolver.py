"""DependencyResolver — Kahn topological sort from requires/produces DAG.

Given a NodeRegistry and pipeline configuration, resolves the execution
order of enabled nodes for a given input_type.  Supports:
- AND dependencies: requires=["a", "b"] — both must be produced
- OR dependencies: requires=[["a", "b"]] — at least one must be produced
- is_terminal nodes auto-connected from all leaf (non-terminal) nodes
- Conflict detection: same asset produced by 2+ nodes with overlapping input_types
- Cycle detection via Kahn's algorithm
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from backend.graph.descriptor import NodeDescriptor
from backend.graph.registry import NodeRegistry

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPipeline:
    """Output of DependencyResolver — everything PipelineBuilder needs."""

    ordered_nodes: list[NodeDescriptor]
    edges: list[tuple[str, str]]
    asset_producers: dict[str, list[str]]  # asset_key → producer node name(s)
    interrupt_before: list[str]  # HITL nodes

    def validate(self) -> None:
        """Raise if the pipeline is inconsistent."""
        names = {d.name for d in self.ordered_nodes}
        for src, dst in self.edges:
            if src not in names:
                raise ValueError(f"Edge source '{src}' not in ordered_nodes")
            if dst not in names:
                raise ValueError(f"Edge destination '{dst}' not in ordered_nodes")


class DependencyResolver:
    """Resolve node execution order from registry + config."""

    @staticmethod
    def resolve(
        reg: NodeRegistry,
        pipeline_config: dict[str, dict],
        input_type: str | None = None,
    ) -> ResolvedPipeline:
        """Resolve the full pipeline for the given input_type.

        Steps:
        1. Filter: enabled + input_type match
        2. Build asset→producers mapping (detect conflicts)
        3. Build adjacency from requires/produces
        4. Connect leaf nodes → terminal nodes
        5. Kahn topological sort
        6. Collect HITL interrupt_before list
        """
        all_nodes = reg.all()

        # Step 1: filter enabled + input_type
        candidates: dict[str, NodeDescriptor] = {}
        for name, desc in all_nodes.items():
            node_config = pipeline_config.get(name, {})
            if not node_config.get("enabled", True):
                continue
            if input_type and input_type not in desc.input_types:
                continue
            candidates[name] = desc

        if not candidates:
            return ResolvedPipeline(
                ordered_nodes=[], edges=[],
                asset_producers={}, interrupt_before=[],
            )

        # Step 2: asset → producers mapping + conflict detection
        # Multiple producers of the same asset are allowed IFF their
        # input_types are disjoint (mutually exclusive at runtime).
        asset_producers: dict[str, list[str]] = defaultdict(list)
        for name, desc in candidates.items():
            for asset in desc.produces:
                # Check for conflicts with existing producers
                for existing_name in asset_producers[asset]:
                    existing_desc = candidates[existing_name]
                    overlap = set(existing_desc.input_types) & set(desc.input_types)
                    if overlap:
                        raise ValueError(
                            f"Asset conflict: '{asset}' produced by both "
                            f"'{existing_name}' and '{name}' "
                            f"(overlapping input_types: {overlap})"
                        )
                asset_producers[asset].append(name)

        # Step 3: build adjacency from requires/produces
        adjacency: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {name: 0 for name in candidates}
        edges: list[tuple[str, str]] = []
        seen_edges: set[tuple[str, str]] = set()

        def _add_edge(src: str, dst: str) -> None:
            if (src, dst) not in seen_edges and src != dst:
                adjacency[src].append(dst)
                in_degree[dst] += 1
                edges.append((src, dst))
                seen_edges.add((src, dst))

        for name, desc in candidates.items():
            for req in desc.requires:
                if isinstance(req, list):
                    # OR dependency: connect to ALL available producers
                    found_any = False
                    for alt in req:
                        if alt in asset_producers:
                            for producer in asset_producers[alt]:
                                _add_edge(producer, name)
                            found_any = True
                    if not found_any:
                        possible = []
                        for alt in req:
                            producers = reg.find_producers(alt)
                            for p in producers:
                                possible.append(f"'{p.name}' (produces '{alt}')")
                        raise ValueError(
                            f"Node '{name}' requires one of {req}, "
                            f"but none are available. "
                            f"Possible producers: {', '.join(possible) or 'none registered'}"
                        )
                else:
                    # AND dependency
                    if req not in asset_producers:
                        possible = reg.find_producers(req)
                        p_names = [f"'{p.name}'" for p in possible]
                        raise ValueError(
                            f"Node '{name}' requires asset '{req}', "
                            f"but no enabled node produces it. "
                            f"Possible producers: {', '.join(p_names) or 'none registered'}"
                        )
                    for producer in asset_producers[req]:
                        _add_edge(producer, name)

        # Step 4: connect leaf → terminal
        terminal_nodes = [d for d in candidates.values() if d.is_terminal]
        if terminal_nodes:
            for name, desc in candidates.items():
                if desc.is_terminal:
                    continue
                has_outgoing = bool(adjacency.get(name))
                if not has_outgoing:
                    for term in terminal_nodes:
                        _add_edge(name, term.name)

        # Step 5: Kahn topological sort
        queue = sorted(name for name, deg in in_degree.items() if deg == 0)
        ordered: list[str] = []

        while queue:
            node = queue.pop(0)
            ordered.append(node)
            for neighbor in sorted(adjacency.get(node, [])):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort()

        if len(ordered) != len(candidates):
            remaining = set(candidates.keys()) - set(ordered)
            raise ValueError(
                f"Cycle detected in pipeline graph. "
                f"Unresolvable nodes: {remaining}"
            )

        # Step 6: collect HITL
        interrupt_before = [
            name for name in ordered
            if candidates[name].supports_hitl
        ]

        ordered_descs = [candidates[name] for name in ordered]

        result = ResolvedPipeline(
            ordered_nodes=ordered_descs,
            edges=edges,
            asset_producers=dict(asset_producers),
            interrupt_before=interrupt_before,
        )
        result.validate()
        return result

    @staticmethod
    def resolve_all(
        reg: NodeRegistry,
        pipeline_config: dict[str, dict],
    ) -> ResolvedPipeline:
        """Resolve ALL nodes regardless of input_type (for single compiled graph)."""
        return DependencyResolver.resolve(reg, pipeline_config, input_type=None)
