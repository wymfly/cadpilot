## ADDED Requirements

### Requirement: LCEL retry chain wraps all LLM invocations

The system SHALL wrap every LLM call in a LCEL chain with `.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)` to handle transient errors. Text intent chains SHALL additionally use `.with_fallbacks([fallback_chain])` pointing to a secondary model. Vision chains (Qwen-VL-Max) SHALL use retry only (no fallback), since no equivalent cheaper VL model is available.

#### Scenario: Transient rate-limit retried transparently
- **WHEN** an LLM API call returns a rate-limit error on the first attempt
- **THEN** the LCEL retry handler waits with exponential jitter and retries
- **AND** the caller receives a successful result if the retry succeeds within 3 attempts
- **AND** no `job.failed` event is emitted during retry

#### Scenario: Retry exhausted falls back to secondary model
- **WHEN** the primary LLM fails 3 times consecutively
- **THEN** the fallback chain invokes a secondary model (e.g., `gpt-4o-mini`)
- **AND** the operation completes with the fallback model's response
- **AND** the system logs a warning indicating fallback was used

#### Scenario: Fallback also fails
- **WHEN** both primary and fallback LLM chains fail
- **THEN** the LCEL chain raises an exception
- **AND** the enclosing `asyncio.wait_for` block catches it as a node error
- **AND** the node returns `{"status": "failed", "error": str(exc), "failure_reason": "generation_error"}`

### Requirement: asyncio.wait_for enforces absolute timeout per node

The system SHALL wrap each LLM node's LCEL chain invocation in `asyncio.wait_for(timeout=60.0)` to enforce an absolute 60-second budget per node, regardless of retry count.

#### Scenario: LLM call completes within 60 seconds
- **WHEN** `analyze_intent_node` completes the LCEL chain within 60 seconds
- **THEN** the result is applied to `CadJobState` and the next node proceeds normally

#### Scenario: LLM node times out after 60 seconds
- **WHEN** `analyze_intent_node` has not completed after 60 seconds
- **THEN** `asyncio.TimeoutError` is raised inside the node
- **AND** the node catches it and returns `{"status": "failed", "error": "意图解析超时（60s）", "failure_reason": "timeout"}`
- **AND** the stream emits `job.failed` event promptly (not hung)

#### Scenario: Vision analysis node has independent timeout
- **WHEN** `analyze_vision_node` is processing a drawing image via Qwen-VL-Max
- **THEN** a separate 60-second budget applies, independent of any prior node timeouts
- **AND** timeout in this node produces `{"status": "failed", "error": "图纸分析超时（60s）", "failure_reason": "timeout"}`

### Requirement: Typed failure reasons surface in SSE payload

The system SHALL include a structured `failure_reason` field in `job.failed` SSE payloads, distinguishing `timeout`, `rate_limited`, `invalid_json`, and `generation_error` causes.

#### Scenario: Timeout produces typed failure payload
- **WHEN** a node fails due to `asyncio.TimeoutError`
- **THEN** the `job.failed` SSE event data contains `{"failure_reason": "timeout", "message": "...", "node": "<node_name>"}`

#### Scenario: JSON parse error produces typed failure payload
- **WHEN** an LLM returns malformed JSON and `JsonOutputParser` raises
- **THEN** the `job.failed` SSE event contains `{"failure_reason": "invalid_json", "message": "...", "node": "<node_name>"}`
