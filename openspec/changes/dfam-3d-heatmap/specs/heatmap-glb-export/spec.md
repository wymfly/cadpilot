## ADDED Requirements

### Requirement: DfAM GLB export with vertex colors
The system SHALL export a separate `model_dfam.glb` file containing the original mesh geometry with vertex color attributes encoding DfAM analysis results. The COLOR_0 accessor SHALL use VEC4 format (RGBA, unsigned byte normalized). The R channel SHALL encode the normalized risk value (0.0=red/danger, 1.0=green/safe). G and B channels SHALL be set to 0. A channel SHALL be 1.0.

#### Scenario: Successful DfAM GLB generation
- **WHEN** vertex analysis completes for a job
- **THEN** the system SHALL write `outputs/{job_id}/model_dfam.glb` containing the mesh with COLOR_0 vertex attribute

#### Scenario: DfAM GLB URL in job result
- **WHEN** DfAM analysis is complete
- **THEN** the job result SHALL include `dfam_glb_url` field pointing to `/outputs/{job_id}/model_dfam.glb`

### Requirement: Analysis metadata in GLB extras
Each mesh in the DfAM GLB SHALL include analysis metadata in its own `extras` field (per-mesh, not scene-level), containing: `analysis_type` ("wall_thickness" | "overhang"), `threshold` (mm or degrees), `min_value`, `max_value`, `vertices_at_risk_count`, `vertices_at_risk_percent`.

#### Scenario: Metadata readable by frontend
- **WHEN** the frontend loads the DfAM GLB
- **THEN** each mesh's extras metadata SHALL be accessible via `mesh.userData` in Three.js (not `gltf.scene.userData`)

### Requirement: Dual analysis encoding
The DfAM GLB SHALL support encoding both wall thickness and overhang analysis. The system SHALL export a single GLB with two named meshes: `mesh.name = "wall_thickness"` and `mesh.name = "overhang"`. Each mesh SHALL carry identical geometry but different COLOR_0 vertex attributes. The active analysis type SHALL be selectable by the frontend by toggling mesh visibility based on `mesh.name`.

#### Scenario: Switching between analysis types
- **WHEN** the user toggles from wall thickness to overhang view
- **THEN** the frontend SHALL hide the mesh named "wall_thickness" and show the mesh named "overhang" without re-fetching the GLB

#### Scenario: Frontend mesh identification
- **WHEN** the frontend loads the DfAM GLB via GLTFLoader
- **THEN** it SHALL find the two meshes by `mesh.name` ("wall_thickness" / "overhang") and read per-mesh `userData` for metadata
