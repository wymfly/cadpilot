## MODIFIED Requirements

### Requirement: Unified StateGraph manages CAD Job lifecycle

The system SHALL implement a single `CadJobStateGraph` using LangGraph `StateGraph` to orchestrate the complete lifecycle for all three input types: text, drawing, and organic.

`CadJobState` SHALL include two additional fields:
- `generated_code: str | None` — the CadQuery Python source code produced by generation nodes
- `parent_job_id: str | None` — link to the parent Job for forked text generations

#### Scenario: Generation nodes save code to state
- **WHEN** `generate_step_text_node` or `generate_step_drawing_node` completes successfully
- **THEN** the node SHALL set `generated_code` in the returned state dict
- **AND** `finalize_node` SHALL persist `generated_code` to `JobModel.generated_code`

#### Scenario: Fork job initializes parent_job_id in state
- **WHEN** POST /api/v1/jobs is called with `parent_job_id` in the request body
- **THEN** `create_job_node` SHALL set `state["parent_job_id"]` to the provided value
- **AND** `finalize_node` SHALL persist `parent_job_id` to `JobModel.parent_job_id`

#### Scenario: Finalize persists code even on postprocess failure
- **WHEN** a job fails during postprocess (printability, convert) but generation succeeded
- **THEN** `finalize_node` SHALL still persist `generated_code` to DB if non-null in state
