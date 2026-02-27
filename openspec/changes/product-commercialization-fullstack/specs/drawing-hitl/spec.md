## ADDED Requirements

### Requirement: Drawing path HITL pause after DrawingSpec extraction

The system SHALL pause the drawing generation pipeline after Stage 1 (DrawingAnalyzer produces DrawingSpec) and wait for user confirmation before proceeding to code generation.

#### Scenario: Normal drawing upload flow
- **WHEN** a user uploads an engineering drawing via POST /generate/drawing
- **THEN** the system calls `analyze_drawing()` (Stage 1 only) to extract DrawingSpec
- **AND** sends an SSE event with status `drawing_spec_ready` containing the full DrawingSpec JSON
- **AND** sets the job status to `awaiting_drawing_confirmation`
- **AND** the first SSE stream ends (pipeline is split, not paused)
- **AND** does NOT proceed to Stage 2 until the user confirms via a separate confirm endpoint

#### Scenario: Pipeline resumes after confirmation
- **WHEN** a user calls POST /generate/drawing/{job_id}/confirm
- **THEN** the system calls `generate_from_drawing_spec()` (Stage 1.5-4) with the confirmed DrawingSpec and original image data
- **AND** a new SSE stream is opened for the generation progress
- **AND** the confirmed DrawingSpec is saved to the job's `drawing_spec_confirmed` field

#### Scenario: User confirms DrawingSpec without changes
- **WHEN** a user calls POST /generate/drawing/{job_id}/confirm with the original DrawingSpec and disclaimer_accepted=true
- **THEN** the system calls `generate_from_drawing_spec()` to resume the V2 pipeline from Stage 1.5 (ModelingStrategist → CodeGenerator → execution → SmartRefiner)

#### Scenario: User edits DrawingSpec before confirming
- **WHEN** a user modifies dimension values or feature parameters in the DrawingSpec and calls confirm
- **THEN** the system uses the user-confirmed DrawingSpec (not the original AI-extracted version) for code generation
- **AND** records each field-level change as a user_correction entry

#### Scenario: User does not accept disclaimer
- **WHEN** a user calls confirm with disclaimer_accepted=false
- **THEN** the system returns HTTP 400 with message "免责声明必须接受后方可继续生成"

### Requirement: DrawingSpec visualization and editing UI

The system SHALL render the AI-extracted DrawingSpec in an editable form, showing part type, dimensions, features, and confidence scores.

#### Scenario: DrawingSpec review page renders
- **WHEN** the SSE event `drawing_spec_ready` is received
- **THEN** the frontend displays: identified part type with confidence percentage, a table of dimension parameters (editable number inputs), a list of identified features, and the disclaimer checkbox

#### Scenario: Dimension editing
- **WHEN** a user changes a dimension value (e.g., outer_diameter from 50 to 55)
- **THEN** the changed field is visually highlighted
- **AND** the confirm button sends the updated DrawingSpec

### Requirement: Disclaimer confirmation for industrial use

The system SHALL require users to accept a disclaimer before proceeding with generation from drawing input, acknowledging that AI-extracted dimensions may contain errors.

#### Scenario: Disclaimer text and checkbox
- **WHEN** the DrawingSpec review page is shown
- **THEN** a disclaimer block is displayed containing: "AI 识别结果仅供参考", acknowledgment that dimensions may have errors, statement that generated models require manual verification before production use, and a checkbox that MUST be checked before the confirm button becomes active

### Requirement: User correction data collection

The system SHALL record every field-level modification a user makes to a DrawingSpec during HITL confirmation, for future model fine-tuning data.

#### Scenario: Correction recorded
- **WHEN** a user changes `overall_dimensions.diameter` from 50 to 55 and confirms
- **THEN** a user_correction record is created with job_id, field_path="overall_dimensions.diameter", original_value="50", corrected_value="55"
- **AND** the correction is persisted to `backend/data/corrections/{job_id}.json` immediately (mandatory, not optional)

#### Scenario: No corrections made
- **WHEN** a user confirms the DrawingSpec without any changes
- **THEN** no user_correction records are created for that job
