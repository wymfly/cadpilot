## ADDED Requirements

### Requirement: Runtime node skip via pipeline_config state

The system SHALL compile all registered nodes into the LangGraph graph regardless of their `enabled` state, and SHALL skip disabled nodes at runtime by checking `state["pipeline_config"][node_name]["enabled"]` in the `_wrap_node()` wrapper. When a node is skipped, it SHALL emit a `node.skipped` SSE event and a trace entry, then return an empty dict without executing any strategy logic.

#### Scenario: Node disabled in pipeline_config skips at runtime
- **WHEN** a Job is created with `pipeline_config={"mesh_repair": {"enabled": false}}`
- **THEN** the graph contains the `mesh_repair` node (compiled in)
- **AND** when execution reaches `mesh_repair`, `_wrap_node()` detects `enabled=false`
- **AND** `_wrap_node()` dispatches `node.started` SSE event (for timeline tracking)
- **AND** `_wrap_node()` dispatches `node.skipped` SSE event with `{"node": "mesh_repair", "reason": "disabled"}`
- **AND** the node returns `{}` without executing its strategy
- **AND** a log message "Node mesh_repair skipped (disabled)" is emitted at INFO level
- **AND** a trace entry `{"event": "node.skipped", "node": "mesh_repair"}` is recorded

#### Scenario: Node enabled by default when not specified
- **WHEN** a Job is created with `pipeline_config={}` (empty config)
- **THEN** all nodes execute normally (enabled defaults to `true`)

#### Scenario: Resolver supports include_disabled parameter
- **WHEN** `DependencyResolver.resolve_all()` is called with `include_disabled=True` (default)
- **THEN** all nodes are included in the resolved node list regardless of `enabled` state
- **AND** the graph topology includes disabled nodes with their edges intact

#### Scenario: Resolver can filter disabled for preview
- **WHEN** `DependencyResolver.resolve_all()` is called with `include_disabled=False`
- **THEN** nodes with `enabled=false` in `pipeline_config` are excluded from the resolved list
- **AND** this mode is used by the validate endpoint for effective topology preview

### Requirement: Validate endpoint respects enabled for preview

The `POST /api/v1/pipeline/validate` endpoint SHALL use `resolve_all(include_disabled=False)` to compute the preview topology, showing the user which nodes would actually execute.

#### Scenario: Validate shows effective topology excluding disabled nodes
- **WHEN** `POST /pipeline/validate` is called with `config={"mesh_repair": {"enabled": false}}`
- **THEN** the response `topology` list does NOT include `mesh_repair`
- **AND** the response `valid` field reflects whether the remaining topology is viable

#### Scenario: All nodes disabled returns invalid
- **WHEN** `POST /pipeline/validate` is called with all nodes `enabled=false`
- **THEN** the response returns `{"valid": false, "error": "至少需要启用一个节点"}`
- **AND** the response `node_count` is 0
