## MODIFIED Requirements

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

#### Scenario: Organic post-confirm routes to mesh processing pipeline
- **WHEN** `confirm_with_user_node` resumes for an organic input type
- **THEN** the Graph routes to `generate_organic_mesh_node` → `mesh_healer_node` → `mesh_scale_node` → downstream nodes → `finalize_node`
- **AND** `mesh_healer_node` replaces the previous `mesh_repair` stub with full dual-channel mesh healing

#### Scenario: Shared postprocess nodes execute once
- **WHEN** either `generate_step_text_node` or `generate_step_drawing_node` completes
- **THEN** `convert_step_to_preview()` runs exactly once to produce the GLB file
- **AND** `check_printability()` runs exactly once to produce the DfAM report
- **AND** `finalize_node` updates DB to COMPLETED and closes the stream

## RENAMED Requirements

### Requirement: mesh_repair node renamed to mesh_healer
- **FROM:** `mesh_repair` node (stub, pass-through)
- **TO:** `mesh_healer` node (full dual-channel implementation with algorithm + neural strategies)
