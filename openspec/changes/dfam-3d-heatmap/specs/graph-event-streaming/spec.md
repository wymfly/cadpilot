## MODIFIED Requirements

### Requirement: Pipeline node lifecycle events
The graph event streaming system SHALL dispatch `node.started` and `node.completed` events for all pipeline nodes, including the newly added `analyze_dfam` node. The `analyze_dfam` node SHALL emit `node.completed` with `elapsed_ms` and `reasoning` fields, consistent with existing M3 @timed_node behavior. The `outputs_summary` SHALL include `vertices_analyzed`, `vertices_at_risk_percent`, and `analysis_types` fields.

#### Scenario: DfAM node lifecycle events
- **WHEN** the `analyze_dfam` node executes during a job pipeline
- **THEN** the system SHALL dispatch `node.started` with `{node: "analyze_dfam"}` followed by `node.completed` with `{node: "analyze_dfam", elapsed_ms: <number>, reasoning: {wall_thickness_range, overhang_range, decimation_applied}, outputs_summary: {vertices_analyzed, vertices_at_risk_percent}}`

#### Scenario: DfAM node graceful degradation
- **WHEN** the `analyze_dfam` node encounters an error (e.g., mesh loading error, trimesh crash)
- **THEN** the node SHALL catch the exception internally and return `{dfam_glb_url: null, dfam_stats: null}` with `_reasoning: {error: <message>}`. The `@timed_node` decorator SHALL dispatch `node.completed` (not `node.failed`) since no exception propagates. The pipeline SHALL continue to `check_printability` which falls back to global-level analysis when `dfam_stats` is null.

Note: This design avoids conflict with `@timed_node`'s re-raise behavior (line 68 of decorators.py). The node handles its own errors to ensure pipeline continuity.
