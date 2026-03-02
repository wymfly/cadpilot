## ADDED Requirements

### Requirement: Correction data cleansing produces valid training records
The system SHALL provide a CLI script that reads UserCorrection records, filters invalid entries, and outputs structured training data.

#### Scenario: Invalid corrections filtered
- **WHEN** the cleansing script processes corrections
- **THEN** records where `original_value == corrected_value` SHALL be excluded
- **AND** records with empty `field_path` or empty `corrected_value` SHALL be excluded

#### Scenario: Unpersisted job corrections handled gracefully
- **WHEN** a correction references a job_id not found in the jobs table (drawing flow in-memory jobs)
- **THEN** the script SHALL skip the record with a warning log
- **AND** SHALL NOT crash or abort the entire cleansing run

#### Scenario: Valid corrections joined with job context
- **WHEN** a valid correction is processed and its job_id exists in the jobs table
- **THEN** the script SHALL join the correction with the parent Job's `intent` and `drawing_spec`
- **AND** output a record with keys: `job_id`, `input_spec` (intent or drawing_spec), `corrections` (list of field_path + corrected_value pairs), `timestamp`

#### Scenario: Output format is JSONL
- **WHEN** the cleansing script completes
- **THEN** the output SHALL be a JSONL file at `data/training/corrections_clean.jsonl`
- **AND** each line SHALL be a valid JSON object

### Requirement: Correction statistics API
The system SHALL expose an API endpoint returning aggregated correction statistics.

#### Scenario: Top corrected fields
- **WHEN** GET /api/v1/corrections/stats is called
- **THEN** the response SHALL include `top_fields`: an array of `{field_path, count, percent}` sorted by count descending
- **AND** the array SHALL contain at most 20 entries

#### Scenario: Stats filtered by part_type
- **WHEN** GET /api/v1/corrections/stats?part_type=ROTATIONAL is called
- **THEN** the response SHALL only include corrections from Jobs whose `intent.part_type` matches the filter
