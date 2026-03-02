## ADDED Requirements

### Requirement: Benchmark _run_single integrates actual V2 pipeline
The system SHALL implement `BenchmarkRunner._run_single()` to invoke the V2 CAD generation pipeline and produce real evaluation metrics.

#### Scenario: Single case runs V2 pipeline
- **WHEN** `_run_single(case)` is called with a BenchmarkCase
- **THEN** the system SHALL call `generate_step_from_2d_cad_image(case.drawing_path, output_filepath=temp_path)`
- **AND** the result SHALL include `compiled=True` if STEP file is generated without exception

#### Scenario: Parameter accuracy computed against expected spec
- **WHEN** the V2 pipeline returns a DrawingSpec
- **THEN** the system SHALL compare numeric dimensions against `case.expected_spec`
- **AND** `param_accuracy` SHALL be the ratio of dimensions within 10% tolerance

#### Scenario: Bounding box match validated
- **WHEN** the generated STEP file exists and `case.expected_bbox` is provided
- **THEN** the system SHALL extract bounding box from the STEP file
- **AND** `bbox_match` SHALL be True if all axis dimensions match within 15% tolerance

#### Scenario: Pipeline failure classified
- **WHEN** the V2 pipeline raises an exception
- **THEN** the system SHALL call `classify_failure(exc)` to categorize the error
- **AND** `BenchmarkResult.failure_category` SHALL be set accordingly
- **AND** `duration_s` SHALL reflect actual elapsed time including the failed attempt

### Requirement: Benchmark dataset format supports text cases
The system SHALL extend `BenchmarkCase` to support text-input cases alongside drawing-input cases.

#### Scenario: Text case loaded from JSON
- **WHEN** a benchmark case JSON contains `input_type: "text"` and `input_text` field
- **THEN** the system SHALL use `generate_step_v2(input_text, output_filepath=temp_path)` for generation
- **AND** `drawing_path` MAY be null for text cases
