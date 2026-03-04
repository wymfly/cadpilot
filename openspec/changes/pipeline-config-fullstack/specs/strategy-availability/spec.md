## ADDED Requirements

### Requirement: Strategy availability endpoint

The system SHALL expose a `GET /api/v1/pipeline/strategy-availability` endpoint that returns the runtime availability status of each strategy for each node. Each strategy's `check_available()` SHALL be called with the actual `config_model` instance (populated from current pipeline_config or defaults), not a bare `BaseNodeConfig()`.

#### Scenario: All strategies available
- **WHEN** `GET /pipeline/strategy-availability` is called
- **AND** all strategy instances return `check_available() == True`
- **THEN** the response contains each node with strategies and `{"available": true}` for each

#### Scenario: Strategy unavailable with reason
- **WHEN** a strategy's `check_available()` returns `False`
- **AND** the strategy instance has `unavailable_reason = "API Key 未配置"`
- **THEN** the response for that strategy contains `{"available": false, "reason": "API Key 未配置"}`

#### Scenario: Strategy instantiation error
- **WHEN** a strategy class raises an exception during `__init__` or `check_available()`
- **THEN** the response for that strategy contains `{"available": false, "reason": "<exception message>"}`

#### Scenario: Strategy checked with actual config
- **WHEN** a strategy's `check_available()` depends on config values (e.g., API endpoint URL)
- **THEN** the endpoint instantiates the strategy with `config=desc.config_model()` (using defaults from Pydantic model)
- **AND** the availability check reflects actual runtime conditions

#### Scenario: Nodes without strategies are excluded
- **WHEN** a node has no registered strategies (`desc.strategies` is empty or None)
- **THEN** that node is not included in the response

### Requirement: Frontend strategy availability integration

The frontend SHALL fetch strategy availability on page load and use it to disable unavailable strategy options in the NodeConfigCard Select component.

#### Scenario: Unavailable strategy shown as disabled with tooltip
- **WHEN** the strategy-availability API returns `{"hunyuan3d": {"available": false, "reason": "API Key 未配置"}}`
- **THEN** the `hunyuan3d` option in the strategy Select is disabled
- **AND** hovering shows a Tooltip with "API Key 未配置"
