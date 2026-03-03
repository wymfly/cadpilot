## ADDED Requirements

### Requirement: SmartRefiner modeled as LangGraph subgraph

The system SHALL implement a `build_refiner_subgraph()` function in `backend/graph/subgraphs/refiner.py` that returns a compiled `CompiledStateGraph` modeling the Compare→Fix→Re-execute cycle as a LangGraph subgraph with up to `max_rounds` iterations.

#### Scenario: Subgraph executes one refinement round
- **WHEN** the subgraph is invoked with `RefinerState` containing code, step_path, drawing_spec, image_path, and `round=0, max_rounds=3`
- **THEN** the subgraph SHALL execute: `static_diagnose → render → vl_compare → route_verdict`
- **AND** if verdict is "fail": `coder_fix → re_execute → increment_round → route_verdict`
- **AND** if verdict is "pass": exit subgraph

#### Scenario: Subgraph exits after max rounds
- **WHEN** `round >= max_rounds` after a "fail" verdict
- **THEN** the subgraph SHALL exit with the current code (best effort)
- **AND** the final `verdict` SHALL be "max_rounds_reached"

#### Scenario: Subgraph dispatches SSE events per round
- **WHEN** each refinement round begins
- **THEN** the `vl_compare` node SHALL dispatch `job.refining` SSE event with `{"round": N, "max_rounds": M, "status": "comparing"}`
- **AND** the `coder_fix` node SHALL dispatch `job.refining` with `{"round": N, "status": "fixing"}`

#### Scenario: Subgraph supports checkpoint recovery
- **WHEN** the process crashes after `vl_compare` completes but before `coder_fix` runs
- **THEN** resuming the graph SHALL continue from `coder_fix` with the saved comparison result
- **AND** the VL model SHALL NOT be re-invoked for the same round

### Requirement: RefinerState is independent of CadJobState

The system SHALL define `RefinerState` as an independent `TypedDict` with explicit fields, mapped to/from `CadJobState` via helper functions at subgraph entry/exit.

#### Scenario: State mapping at subgraph entry
- **WHEN** `generate_step_drawing_node` invokes the refiner subgraph
- **THEN** it SHALL construct `RefinerState` from `CadJobState` fields: `generated_code → code`, `step_path → step_path`, `drawing_spec → drawing_spec`, `image_path → image_path`
- **AND** set `round=0`, `max_rounds=config.max_refinements`, `verdict="pending"`

#### Scenario: State mapping at subgraph exit
- **WHEN** the refiner subgraph completes
- **THEN** the caller SHALL extract `RefinerState["code"]` as the refined code
- **AND** if `verdict == "pass"`, the code is final
- **AND** if `verdict == "max_rounds_reached"`, the code is best-effort

### Requirement: Static diagnosis node provides Layer 1/2/2.5 diagnostics

The system SHALL implement a `static_diagnose` node within the refiner subgraph that runs Layer 1 (parameter validation), Layer 2 (bounding box), and Layer 2.5 (topology) checks, storing results in `RefinerState["static_notes"]`.

#### Scenario: Static diagnosis with valid STEP
- **WHEN** `static_diagnose` runs with a valid STEP file
- **THEN** it SHALL populate `static_notes` with any mismatches from `validate_code_params()`, `validate_bounding_box()`, and optionally `compare_topology()`
- **AND** it SHALL NOT make any LLM calls

#### Scenario: Static diagnosis with missing STEP
- **WHEN** `static_diagnose` runs but the STEP file does not exist
- **THEN** `static_notes` SHALL be empty
- **AND** the subgraph SHALL continue to `vl_compare` (diagnosis is advisory only)

### Requirement: Rollback tracking within subgraph

The system SHALL integrate `RollbackTracker` within the refiner subgraph to detect score degradation after each fix round.

#### Scenario: Code fix degrades geometry score
- **WHEN** `re_execute` node completes and the new geometry score is lower than the previous round
- **THEN** the subgraph SHALL rollback to the previous round's code
- **AND** dispatch `job.refining` SSE event with `{"round": N, "status": "rollback"}`
- **AND** re-execute the rolled-back code to restore the STEP file

#### Scenario: Code fix improves or maintains score
- **WHEN** `re_execute` node completes and the geometry score is >= previous round
- **THEN** the subgraph SHALL accept the new code and continue to the next round or exit
