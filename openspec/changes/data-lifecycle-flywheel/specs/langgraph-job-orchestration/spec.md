## MODIFIED Requirements

### Requirement: Unified StateGraph manages CAD Job lifecycle

The system SHALL implement a single `CadJobStateGraph` using LangGraph `StateGraph` to orchestrate the complete lifecycle (create → analyze → HITL → generate → postprocess → complete) for all three input types: text, drawing, and organic.

`CadJobState` SHALL include two additional fields:
- `generated_code: str | None` — the CadQuery Python source code produced by generation nodes
- `parent_job_id: str | None` — link to the parent Job for forked generations

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

#### Scenario: Generation nodes save code to state
- **WHEN** `generate_step_text_node` or `generate_step_drawing_node` completes successfully
- **THEN** the node SHALL set `generated_code` in the returned state dict
- **AND** `finalize_node` SHALL persist `generated_code` to `JobModel.generated_code`

#### Scenario: Fork job initializes parent_job_id in state
- **WHEN** POST /api/v1/jobs is called with `parent_job_id` in the request body
- **THEN** `create_job_node` SHALL set `state["parent_job_id"]` to the provided value
- **AND** `finalize_node` SHALL persist `parent_job_id` to `JobModel.parent_job_id`
