## ADDED Requirements

### Requirement: Text-to-3D generation
The system SHALL accept a text prompt and generate a 3D mesh via cloud AI API (Tripo3D primary, Hunyuan3D fallback).

#### Scenario: Successful text-to-3D generation
- **WHEN** user submits `POST /api/generate/organic` with `prompt: "高尔夫球头"` and `quality_mode: "standard"`
- **THEN** system returns SSE stream with events: `created → analyzing → generating → post_processing → completed`, and the `completed` event includes `model_url` pointing to a valid GLB file

#### Scenario: Provider fallback on failure
- **WHEN** primary provider (Tripo3D) fails or times out
- **THEN** system automatically retries with fallback provider (Hunyuan3D) and completes generation

#### Scenario: Provider unavailable
- **WHEN** all providers are unavailable
- **THEN** system returns SSE event with `status: "failed"` and a descriptive error message

### Requirement: Image-to-3D generation
The system SHALL accept an image upload (with optional text prompt) and generate a 3D mesh.

#### Scenario: Successful image-to-3D generation
- **WHEN** user submits `POST /api/generate/organic/upload` with an image file and optional `prompt`
- **THEN** system generates a 3D mesh from the image and returns SSE stream through to `completed`

#### Scenario: Image upload validation
- **WHEN** user uploads a file exceeding 10MB or with unsupported MIME type (not image/png, image/jpeg, image/webp)
- **THEN** system returns HTTP 422 with descriptive error before starting any generation

### Requirement: OrganicSpec construction via LLM
The system SHALL use an LLM to translate user's Chinese prompt into an English prompt suitable for 3D generation APIs, and extract shape category and suggested bounding box.

#### Scenario: Chinese prompt translation
- **WHEN** user provides prompt "高尔夫发球木球头，流线型，碳纤维质感"
- **THEN** OrganicSpec contains `prompt_en` with an English translation and `shape_category` identifying the object type

### Requirement: Mesh post-processing pipeline
The system SHALL apply a post-processing pipeline to AI-generated meshes: repair → scale → boolean cuts → validation.

#### Scenario: Full post-processing with engineering cuts
- **WHEN** a raw mesh is generated and constraints include `flat_bottom` and a `hole` cut
- **THEN** the processed mesh has a flat bottom surface, a cylindrical hole within tolerance (±0.2mm standard, ±0.1mm high) at the specified position/diameter, is watertight, and has non-zero volume

#### Scenario: Draft mode skips boolean cuts
- **WHEN** `quality_mode` is `"draft"` and constraints include engineering cuts
- **THEN** system applies only repair and scaling, skipping boolean cuts, for faster output

### Requirement: Mesh repair
The system SHALL repair AI-generated meshes using PyMeshLab to fix non-manifold edges/vertices, unify normals, and close small holes.

#### Scenario: Non-manifold mesh repaired
- **WHEN** AI generates a mesh with non-manifold edges
- **THEN** post-processor repairs the mesh and `mesh_stats.has_non_manifold` is `false` in the output

### Requirement: Bounding box scaling
The system SHALL scale the AI-generated mesh to fit within the user-specified bounding box while preserving aspect ratio.

#### Scenario: Mesh scaled to target dimensions
- **WHEN** user specifies `bounding_box: [80, 80, 60]` mm
- **THEN** the processed mesh fits within 80×80×60 mm with less than 5% deviation

### Requirement: Boolean cut operations via manifold3d
The system SHALL use manifold3d for boolean difference operations to create engineering interfaces (flat bottom, holes, slots) on organic meshes.

#### Scenario: Flat bottom cut
- **WHEN** constraints include `{ "type": "flat_bottom" }`
- **THEN** the mesh bottom is planar, suitable for stable 3D printing placement

#### Scenario: Precision hole cut
- **WHEN** constraints include `{ "type": "hole", "diameter": 10, "depth": 25, "direction": "bottom" }`
- **THEN** a cylindrical hole of approximately 10mm diameter (±0.2mm for standard, ±0.1mm for high) and 25mm depth is cut from the bottom of the mesh

#### Scenario: Boolean failure graceful degradation
- **WHEN** manifold3d boolean operation fails on a problematic mesh
- **THEN** system returns the repaired-and-scaled mesh without boolean cuts, with a warning in `mesh_stats.repairs_applied`

### Requirement: Mesh quality validation
The system SHALL validate the processed mesh for watertightness, non-zero volume, and bounding box accuracy.

#### Scenario: Quality validation passes
- **WHEN** post-processing completes successfully
- **THEN** `mesh_stats` includes `is_watertight`, `volume_cm3`, `bounding_box`, `vertex_count`, `face_count`, and `boolean_cuts_applied`

### Requirement: Multi-format export
The system SHALL export the processed mesh in STL, 3MF, and GLB formats.

#### Scenario: All formats available on completion
- **WHEN** generation completes successfully
- **THEN** `completed` event includes `model_url` (GLB), `stl_url`, and `threemf_url`

### Requirement: Job lifecycle management
The system SHALL persist organic generation job state, allowing clients to query job status and recover from connection drops.

#### Scenario: Job status query
- **WHEN** client calls `GET /api/generate/organic/{job_id}`
- **THEN** response includes current job status, progress, and completed artifacts (model_url, stl_url) if available

#### Scenario: SSE reconnection
- **WHEN** client SSE connection drops during generation and client reconnects via `GET /api/generate/organic/{job_id}`
- **THEN** client receives current state and can resume listening for updates

### Requirement: Provider abstraction layer
The system SHALL abstract 3D generation providers behind a `MeshProvider` interface supporting `generate()` and `check_health()`.

#### Scenario: Provider health check
- **WHEN** `GET /api/generate/organic/providers` is called
- **THEN** response lists available providers with their health status

### Requirement: Quality mode configuration
The system SHALL support three quality modes: `draft`, `standard`, `high`, each mapping to different API settings and post-processing depth.

#### Scenario: Quality modes affect processing
- **WHEN** `quality_mode` is `"high"`
- **THEN** system uses high-precision API settings, applies all post-processing steps including secondary smoothing
