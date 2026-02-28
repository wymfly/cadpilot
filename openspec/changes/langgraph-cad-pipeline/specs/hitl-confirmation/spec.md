## MODIFIED Requirements

### Requirement: Drawing path HITL pause after DrawingSpec extraction

The system SHALL pause the drawing generation pipeline after Stage 1 (DrawingAnalyzer produces DrawingSpec) using LangGraph `interrupt_before=["confirm_with_user_node"]` to pause before the confirm node, and SHALL resume via `Command(resume=...)` when the user confirms. The `job.awaiting_confirmation` event is dispatched by the preceding analysis node (not the confirm node itself, since `interrupt_before` pauses execution before the node runs).

#### Scenario: Normal drawing upload flow
- **WHEN** a user uploads an engineering drawing via POST /api/v1/jobs/upload
- **THEN** the Graph executes `analyze_vision_node` to extract DrawingSpec
- **AND** `analyze_vision_node` dispatches `job.spec_ready` and `job.awaiting_confirmation` SSE events before completing
- **AND** the Graph pauses via `interrupt_before` at `confirm_with_user_node` boundary
- **AND** the checkpoint is persisted to `AsyncSqliteSaver` at the interrupt point

#### Scenario: Pipeline resumes after confirmation via Command
- **WHEN** a user calls POST /api/v1/jobs/{job_id}/confirm with confirmed params
- **THEN** the endpoint calls `cad_graph.astream_events(Command(resume=body.model_dump()), config=config, version="v2")`
- **AND** the Graph resumes from the `confirm_with_user_node` checkpoint
- **AND** a new SSE stream is returned for the generation progress
- **AND** the confirmed params are stored in `CadJobState.confirmed_spec`

#### Scenario: User confirms DrawingSpec without changes
- **WHEN** a user calls POST /api/v1/jobs/{id}/confirm with the original DrawingSpec and `disclaimer_accepted=true`
- **THEN** the Graph resumes and routes to `generate_step_drawing_node`
- **AND** `generate_step_from_spec()` is called with the confirmed DrawingSpec

#### Scenario: User edits DrawingSpec before confirming
- **WHEN** a user modifies dimension values or feature parameters in the DrawingSpec and calls confirm
- **THEN** the Graph state receives the user-confirmed spec via `Command(resume={...})`
- **AND** `generate_step_drawing_node` uses `state["confirmed_spec"]` (not the original AI-extracted version)
- **AND** field-level corrections are recorded (see User correction data collection requirement)

#### Scenario: User does not accept disclaimer
- **WHEN** a user calls confirm with `disclaimer_accepted=false`
- **THEN** the system returns HTTP 400 with message "免责声明必须接受后方可继续生成"
- **AND** the Graph run remains in the interrupted state (not resumed)

#### Scenario: Process restart does not lose HITL state
- **WHEN** the server restarts while a job is interrupted at `confirm_with_user_node`
- **THEN** the next POST /api/v1/jobs/{id}/confirm request finds the checkpoint in `AsyncSqliteSaver`
- **AND** `Command(resume=...)` successfully restores execution context
- **AND** the job completes normally without re-running the `analyze_vision_node`

### Requirement: User correction data collection

The system SHALL record every field-level modification a user makes to a DrawingSpec during HITL confirmation, for future model fine-tuning data.

#### Scenario: Correction recorded to both JSON and DB
- **WHEN** a user changes `overall_dimensions.diameter` from 50 to 55 and confirms
- **THEN** a `user_correction` record is created with `job_id`, `field_path="overall_dimensions.diameter"`, `original_value="50"`, `corrected_value="55"`
- **AND** the correction is persisted to `backend/data/corrections/{job_id}.json` immediately
- **AND** the correction is ALSO written to the `corrections` DB table via `create_correction()` within the same confirm flow
- **AND** both writes are attempted; failure of either is logged at WARNING level (not silently swallowed)

#### Scenario: No corrections made
- **WHEN** a user confirms the DrawingSpec without any changes
- **THEN** no `user_correction` records are created for that job

## REMOVED Requirements

### Requirement: Drawing path HITL pause after DrawingSpec extraction (HTTP state machine variant)

**Reason**: The HTTP-state-machine approach (split into two separate HTTP requests with no shared execution context) is replaced by the LangGraph `interrupt()` / `Command(resume=...)` mechanism which maintains full execution context via `AsyncSqliteSaver` checkpoints.

**Migration**: Replace calls to the old split-pipeline pattern with `cad_graph.astream_events(Command(resume=...))`. The `/generate/drawing/{job_id}/confirm` endpoint is deprecated; use POST `/api/v1/jobs/{id}/confirm` instead.
