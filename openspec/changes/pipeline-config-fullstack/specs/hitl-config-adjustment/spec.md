## ADDED Requirements

### Requirement: HITL confirm dialog with pipeline config editing

The HITL ConfirmDialog SHALL include a collapsible "高级配置" section that allows users to modify pipeline configuration for nodes that have not yet executed.

#### Scenario: Only unexecuted nodes shown in HITL config panel
- **WHEN** the graph is interrupted at `confirm_with_user_node` after `analysis_node` has executed
- **THEN** the ConfirmDialog's "高级配置" section shows NodeConfigCards only for nodes after the interrupt point
- **AND** `analysis_node` is NOT shown (already executed)

#### Scenario: User changes strategy during HITL
- **WHEN** the user changes `generate_raw_mesh.strategy` from `hunyuan3d` to `tripo3d` in the HITL config panel
- **AND** clicks confirm
- **THEN** the confirm request includes `pipeline_config_updates: {"generate_raw_mesh": {"strategy": "tripo3d"}}`
- **AND** the graph resumes with the updated strategy

#### Scenario: Config changes deep-merged into state
- **WHEN** the confirm request includes `pipeline_config_updates: {"mesh_repair": {"timeout": 300}}`
- **AND** the existing `pipeline_config` has `{"mesh_repair": {"enabled": true, "strategy": "manifold"}}`
- **THEN** the merged config is `{"mesh_repair": {"enabled": true, "strategy": "manifold", "timeout": 300}}`
- **AND** subsequent nodes read the merged config via `NodeContext.from_state()`

#### Scenario: HITL config changes validated before confirm
- **WHEN** the user modifies config in the HITL dialog and clicks confirm
- **THEN** the frontend calls `POST /pipeline/validate` with the merged config before sending confirm request
- **AND** if validation fails, shows error in the dialog and blocks confirm
- **AND** if validation passes, proceeds with the confirm request
