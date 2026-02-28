## ADDED Requirements

### Requirement: Unified StateGraph manages CAD Job lifecycle

The system SHALL implement a single `CadJobStateGraph` using LangGraph `StateGraph` to orchestrate the complete lifecycle (create → analyze → HITL → generate → postprocess → complete) for all three input types: text, drawing, and organic.

#### Scenario: Text job flows through intent analysis
- **WHEN** a POST /api/v1/jobs request arrives with `input_type=text`
- **THEN** the Graph executes `create_job_node` → `analyze_intent_node` → `confirm_with_user_node`
- **AND** each node transition is persisted to `AsyncSqliteSaver` checkpoint before proceeding

#### Scenario: Drawing job flows through vision analysis
- **WHEN** a POST /api/v1/jobs/upload request arrives with `input_type=drawing`
- **THEN** the Graph executes `create_job_node` → `analyze_vision_node` → `confirm_with_user_node`
- **AND** `analyze_vision_node` wraps `analyze_vision_spec()` via `asyncio.to_thread`

#### Scenario: Organic job skips analysis
- **WHEN** a POST /api/v1/jobs request arrives with `input_type=organic`
- **THEN** the Graph executes `create_job_node` → `stub_organic_node` → `confirm_with_user_node` directly
- **AND** no LLM analysis is performed before presenting confirmation

#### Scenario: Post-confirm generation routes by type
- **WHEN** `confirm_with_user_node` resumes after user confirmation
- **THEN** the Graph routes to `generate_step_text_node` for text input or `generate_step_drawing_node` for drawing input
- **AND** both paths converge at `convert_preview_node` → `check_printability_node` → `finalize_node`

#### Scenario: Organic post-confirm exits Graph for legacy processing
- **WHEN** `confirm_with_user_node` resumes for an organic input type
- **THEN** `route_after_confirm` returns `"organic_external"`
- **AND** the Graph routes to `finalize_node` which marks the Job in DB as `confirmed` (not `completed`)
- **AND** the actual organic generation is delegated to the legacy `/api/generate/organic` endpoint (outside the Graph)
- **AND** a `job.organic_delegated` SSE event is dispatched before the Graph run ends

#### Scenario: Shared postprocess nodes execute once
- **WHEN** either `generate_step_text_node` or `generate_step_drawing_node` completes
- **THEN** `convert_step_to_preview()` runs exactly once to produce the GLB file
- **AND** `check_printability()` runs exactly once to produce the DfAM report
- **AND** `finalize_node` updates DB to COMPLETED and closes the stream

### Requirement: AsyncSqliteSaver enables checkpoint persistence

The system SHALL use `AsyncSqliteSaver` connected to the existing `backend/data/cad3dify.db` for LangGraph checkpoint storage, enabling断点续跑 (resume from checkpoint after process restart).

#### Scenario: Checkpoint tables created automatically
- **WHEN** the application starts and `get_compiled_graph()` is called
- **THEN** LangGraph creates `checkpoints` and `checkpoint_blobs` tables in `cad3dify.db` if they do not exist
- **AND** existing Job tables are NOT affected

#### Scenario: Resume from checkpoint after restart
- **WHEN** a process restart occurs mid-execution and a new request arrives for the same `job_id`
- **THEN** the Graph resumes from the last completed node's checkpoint using `thread_id=job_id`
- **AND** completed nodes are NOT re-executed (checkpoint detected via `CadJobState` fields)

#### Scenario: Idempotent node skips if output exists
- **WHEN** `generate_step_drawing_node` runs after a checkpoint resume
- **THEN** the node checks `state["step_path"]` and whether the file exists at that path
- **AND** if the file exists, the node returns `{}` immediately without re-invoking the CAD pipeline

### Requirement: Node-level error handling produces failed state

The system SHALL propagate node failures as structured state updates, yielding a `job.failed` SSE event and marking the DB Job status as FAILED.

#### Scenario: Node exception captured as state with typed failure_reason
- **WHEN** any Graph node raises an unhandled exception
- **THEN** the node calls `map_exception_to_failure_reason(exc)` to classify the error
- **AND** returns `{"status": "failed", "error": str(exc), "failure_reason": "<type>"}` to the Graph state
- **AND** the `finalize_node` detects `status=failed`, emits a `job.failed` SSE event with `failure_reason` field in payload
- **AND** the DB job record is updated to `status=FAILED` with the error message

#### Scenario: LLM timeout causes failed state
- **WHEN** `asyncio.wait_for` raises `TimeoutError` inside `analyze_intent_node`
- **THEN** the node returns `{"status": "failed", "error": "意图解析超时（60s）", "failure_reason": "timeout"}`
- **AND** the stream emits `job.failed` promptly after the timeout with `failure_reason: "timeout"` in payload

### Requirement: API layer delegates to Graph astream_events

The system SHALL simplify `backend/api/v1/jobs.py` so that POST endpoints call `cad_graph.astream_events()` and yield only `on_custom_event` events as SSE.

#### Scenario: Create job endpoint uses Graph
- **WHEN** POST /api/v1/jobs is called
- **THEN** the endpoint creates a config `{"configurable": {"thread_id": job_id}}`
- **AND** calls `cad_graph.astream_events(initial_state, config=config, version="v2")`
- **AND** yields only events where `event["event"] == "on_custom_event"`

#### Scenario: Confirm endpoint resumes Graph
- **WHEN** POST /api/v1/jobs/{id}/confirm is called
- **THEN** the endpoint calls `cad_graph.astream_events(Command(resume=body.model_dump()), config=config, version="v2")`
- **AND** the Graph continues from the `confirm_with_user_node` interrupt point
