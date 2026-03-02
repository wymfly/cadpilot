## ADDED Requirements

### Requirement: Correction data cleansing produces valid training triples
The system SHALL provide a CLI script that reads UserCorrection records, filters invalid entries, and outputs structured training data.

#### Scenario: Invalid corrections filtered
- **WHEN** the cleansing script processes corrections
- **THEN** records where `original_value == corrected_value` SHALL be excluded
- **AND** records with empty `field_path` or empty `corrected_value` SHALL be excluded

#### Scenario: Training triples generated
- **WHEN** a valid correction is processed
- **THEN** the script SHALL join the correction with the parent Job's `intent`/`drawing_spec` and `generated_code`
- **AND** output a triple: `{input_spec, original_code, corrected_spec_fields}`

#### Scenario: Output format is JSONL
- **WHEN** the cleansing script completes
- **THEN** the output SHALL be a JSONL file at `data/training/corrections_clean.jsonl`
- **AND** each line SHALL be a valid JSON object with keys `job_id`, `input_spec`, `corrections`, `timestamp`

### Requirement: Correction statistics API
The system SHALL expose an API endpoint returning aggregated correction statistics.

#### Scenario: Top corrected fields
- **WHEN** GET /api/v1/corrections/stats is called
- **THEN** the response SHALL include `top_fields`: an array of `{field_path, count, percent}` sorted by count descending
- **AND** the array SHALL contain at most 20 entries

#### Scenario: Stats filtered by part_type
- **WHEN** GET /api/v1/corrections/stats?part_type=ROTATIONAL is called
- **THEN** the response SHALL only include corrections from Jobs whose `intent.part_type` matches the filter

#### Scenario: Time trend data
- **WHEN** GET /api/v1/corrections/stats?group_by=week is called
- **THEN** the response SHALL include `trend`: an array of `{period, total_corrections, unique_fields}` grouped by ISO week
