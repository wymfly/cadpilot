## ADDED Requirements

### Requirement: Output files organized in three-tier archive structure
The system SHALL organize files under `outputs/{job_id}/` into `input/`, `intermediate/`, and `output/` subdirectories.

#### Scenario: Uploaded images stored in input directory
- **WHEN** a drawing upload is processed by `create_job_node`
- **THEN** the uploaded image SHALL be stored at `outputs/{job_id}/input/{filename}`

#### Scenario: STEP file stored in intermediate directory
- **WHEN** a generation node produces a STEP file
- **THEN** the STEP file SHALL be written to `outputs/{job_id}/intermediate/model.step`

#### Scenario: GLB and DfAM outputs stored in output directory
- **WHEN** `convert_preview_node` produces a GLB file
- **THEN** the GLB SHALL be written to `outputs/{job_id}/output/model.glb`
- **AND** DfAM GLB SHALL be written to `outputs/{job_id}/output/model_dfam.glb`

#### Scenario: LocalFileStorage supports subdir parameter
- **WHEN** `LocalFileStorage.save(job_id, filename, data, subdir="output")` is called
- **THEN** the file SHALL be written to `outputs/{job_id}/output/{filename}`
- **AND** the returned URL path SHALL be `/outputs/{job_id}/output/{filename}`
