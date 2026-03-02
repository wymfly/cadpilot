## ADDED Requirements

### Requirement: Job persists generated CadQuery code
The system SHALL persist the CadQuery Python code generated during STEP creation into `CadJobState.generated_code` and `JobModel.generated_code`, enabling code retrieval via API.

#### Scenario: Text path saves generated code
- **WHEN** `generate_step_text_node` successfully generates a STEP file via SpecCompiler
- **THEN** the node SHALL set `state["generated_code"]` to the Python source code string returned by the compiler
- **AND** the code SHALL be persisted to `JobModel.generated_code` by `finalize_node`

#### Scenario: Drawing path saves generated code
- **WHEN** `generate_step_drawing_node` successfully generates a STEP file via V2 pipeline
- **THEN** the node SHALL set `state["generated_code"]` to the CadQuery code produced by `CodeGeneratorChain`
- **AND** the code SHALL be persisted to `JobModel.generated_code` by `finalize_node`

#### Scenario: API returns generated code in job detail
- **WHEN** GET /api/v1/jobs/{id} is called for a completed job
- **THEN** the response SHALL include a `generated_code` field containing the Python source code
- **AND** the field SHALL be null for failed or in-progress jobs

### Requirement: Fork job preserves version chain via parent_job_id
The system SHALL support creating a new Job derived from an existing one, linked via `parent_job_id`.

#### Scenario: Fork creates a child job
- **WHEN** POST /api/v1/jobs is called with `parent_job_id` in the request body
- **THEN** the system SHALL create a new Job with `JobModel.parent_job_id` set to the given value
- **AND** the child Job SHALL inherit `input_type` and `input_text` from the parent unless overridden

#### Scenario: Job detail includes version chain
- **WHEN** GET /api/v1/jobs/{id} is called for a job that has a `parent_job_id`
- **THEN** the response SHALL include `parent_job_id` field
- **AND** GET /api/v1/jobs/{parent_id} SHALL include a `child_jobs` array listing derived job IDs

#### Scenario: Code file saved alongside STEP
- **WHEN** a generation node completes successfully
- **THEN** the system SHALL write the CadQuery code to `outputs/{job_id}/output/code.py` as a file artifact
