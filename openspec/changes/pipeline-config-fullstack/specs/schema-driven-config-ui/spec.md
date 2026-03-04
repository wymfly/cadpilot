## ADDED Requirements

### Requirement: SchemaForm dynamic form rendering

The frontend SHALL provide a `SchemaForm` component that accepts a JSON Schema (`config_schema`) and dynamically renders Ant Design form controls based on property types.

#### Scenario: Boolean property renders Switch
- **WHEN** `config_schema` contains `{"auto_repair": {"type": "boolean", "description": "自动修复"}}`
- **THEN** `SchemaForm` renders an Ant Design `Switch` component with label "自动修复"

#### Scenario: Number property with min/max renders Slider
- **WHEN** `config_schema` contains `{"timeout": {"type": "integer", "minimum": 10, "maximum": 600}}`
- **THEN** `SchemaForm` renders a `Slider` with range 10-600

#### Scenario: Number property without min/max renders InputNumber
- **WHEN** `config_schema` contains `{"retry_count": {"type": "integer"}}`
- **THEN** `SchemaForm` renders an `InputNumber` component

#### Scenario: String with enum renders Select
- **WHEN** `config_schema` contains `{"format": {"type": "string", "enum": ["STL", "OBJ", "STEP"]}}`
- **THEN** `SchemaForm` renders a `Select` with options STL, OBJ, STEP

#### Scenario: String without enum renders Input
- **WHEN** `config_schema` contains `{"api_endpoint": {"type": "string"}}`
- **THEN** `SchemaForm` renders a text `Input` component

#### Scenario: Sensitive field renders Password input
- **WHEN** `config_schema` contains a property with `"x-sensitive": true`
- **THEN** `SchemaForm` renders an `Input.Password` component

#### Scenario: Fields grouped by x-group
- **WHEN** `config_schema` contains properties with `"x-group": "基本"` and `"x-group": "高级"`
- **THEN** `SchemaForm` groups fields under "基本" and "高级" section headers

#### Scenario: enabled and strategy fields are skipped
- **WHEN** `config_schema` contains `enabled` and `strategy` properties
- **THEN** `SchemaForm` does NOT render them (they are handled by NodeConfigCard header)

#### Scenario: Unsupported type renders read-only display
- **WHEN** `config_schema` contains a property with `"type": "object"` or `"type": "array"`
- **THEN** `SchemaForm` renders a read-only `Typography.Text` showing the JSON value
- **AND** does NOT attempt to render nested form controls (complex types unsupported in v1)

### Requirement: Config schema enhancement — x-sensitive auto-detection

The backend SHALL post-process `config_schema` from Pydantic v2's native `model_json_schema()` to inject `x-sensitive: true` for fields whose names contain `api_key`, `secret`, or `password`. All other schema metadata (description, minimum/maximum, x-group via `json_schema_extra`) is already handled natively by Pydantic v2 and requires no custom extraction logic.

Note: `x-sensitive` is a **UI-only marker** for rendering `Input.Password` in the frontend. It does NOT provide backend security. SSE event payloads SHALL sanitize sensitive field values (mask to `"***"`) to prevent leaking secrets through the event stream.

#### Scenario: Sensitive field auto-detected
- **WHEN** a config_model field name contains `api_key`, `secret`, or `password`
- **THEN** the generated schema property includes `"x-sensitive": true`

#### Scenario: Pydantic v2 native metadata preserved
- **WHEN** a config_model has `Field(description="超时时间（秒）", ge=10, le=600, json_schema_extra={"x-group": "高级"})`
- **THEN** the generated schema property includes `"description": "超时时间（秒）"`, `"minimum": 10`, `"maximum": 600`, `"x-group": "高级"` — all from Pydantic v2's native `model_json_schema()`, no custom extraction needed

#### Scenario: SSE events sanitize sensitive config values
- **WHEN** a node's config contains `api_key: "sk-abc123"`
- **AND** the node dispatches SSE events containing config data
- **THEN** the `api_key` value in the SSE payload is masked as `"***"`

### Requirement: NodeConfigCard with collapsible design

Each node SHALL be rendered as a collapsible card in the CustomPanel, with header containing enabled Switch + node name + strategy Select, and body containing SchemaForm + fallback chain tags.

#### Scenario: Card header shows enabled toggle and strategy selector
- **WHEN** a node `mesh_repair` has `strategies: {"manifold": ..., "trimesh": ...}` and `enabled: true`
- **THEN** the card header shows: [Switch ON] "mesh_repair" [Select: manifold ▾]

#### Scenario: Fallback chain displayed as Tag list
- **WHEN** a node has `fallback_chain: ["hunyuan3d", "tripo3d", "spar3d"]`
- **THEN** the card body shows Tag components in order: hunyuan3d → tripo3d → spar3d

### Requirement: ValidationBanner real-time validation

The frontend SHALL display a ValidationBanner that validates the current pipeline config by calling `POST /pipeline/validate` with 300ms debounce after any config change. The component SHALL use `AbortController` to cancel in-flight requests when a new validation is triggered, preventing stale responses from overwriting current state.

#### Scenario: Valid config shows success banner
- **WHEN** the current config is valid
- **THEN** a green banner shows "✓ 有效 — N 个节点，拓扑: node1 → node2 → ..."

#### Scenario: Invalid config shows error banner
- **WHEN** a core dependency is disabled (e.g., `generate_raw_mesh` depends on `mesh_healer` which is disabled)
- **THEN** a red banner shows "✗ 无效 — generate_raw_mesh 的依赖 mesh_healer 已禁用"

#### Scenario: Debounced validation with request cancellation
- **WHEN** the user rapidly toggles multiple node switches within 300ms
- **THEN** only one validate API call is made after the last change
- **AND** any in-flight previous request is aborted via `AbortController.abort()`
