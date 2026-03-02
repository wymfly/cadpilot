## ADDED Requirements

### Requirement: Job persists generated CadQuery code
The system SHALL persist the CadQuery Python code generated during STEP creation into `CadJobState.generated_code` and `JobModel.generated_code`, enabling code retrieval via API.

#### Scenario: Text path saves generated code
- **WHEN** `generate_step_text_node` successfully generates a STEP file via SpecCompiler
- **THEN** the node SHALL set `state["generated_code"]` to the Python source code string returned by the compiler
- **AND** the code SHALL be persisted to `JobModel.generated_code` by `finalize_node`

#### Scenario: Drawing path saves generated code
- **WHEN** `generate_step_drawing_node` successfully generates a STEP file via V2 pipeline
- **THEN** the node SHALL capture the CadQuery code returned by the modified pipeline function
- **AND** set `state["generated_code"]` to the code string
- **AND** the code SHALL be persisted to `JobModel.generated_code` by `finalize_node`

#### Scenario: API returns generated code in job detail
- **WHEN** GET /api/v1/jobs/{id} is called for a completed job
- **THEN** the response SHALL include a `generated_code` field containing the Python source code
- **AND** the field SHALL be null for failed or in-progress jobs that never reached generation

#### Scenario: Code saved even if postprocess fails
- **WHEN** generation succeeds but a later postprocess node (printability, convert) fails
- **THEN** the `generated_code` SHALL still be persisted to DB (useful for debugging)

### Requirement: V2 pipeline exposes generated code via return value
The system SHALL modify `_run_generate_from_spec()` in `cadpilot/pipeline.py` to return the generated CadQuery code string alongside the STEP file.

#### Scenario: Pipeline returns code alongside STEP
- **WHEN** `_run_generate_from_spec()` completes successfully
- **THEN** the function SHALL return the generated Python code string
- **AND** the calling node SHALL extract and store this code in state

### Requirement: Fork job preserves version chain via parent_job_id (text only)
The system SHALL support creating a new text Job derived from an existing one, linked via `parent_job_id`.

#### Scenario: Fork creates a child job
- **WHEN** POST /api/v1/jobs is called with `parent_job_id` in the request body and `input_type=text`
- **THEN** the system SHALL create a new Job with `JobModel.parent_job_id` set to the given value
- **AND** the child Job SHALL inherit `input_text` from the parent unless overridden

#### Scenario: Fork rejected for non-text types
- **WHEN** POST /api/v1/jobs is called with `parent_job_id` and `input_type` is not `text`
- **THEN** the system SHALL return HTTP 400 with message "Fork is only supported for text jobs"

#### Scenario: Job detail includes parent and children
- **WHEN** GET /api/v1/jobs/{id} is called
- **THEN** the response SHALL include `parent_job_id` (nullable) and `child_job_ids` (list queried by parent_job_id)
