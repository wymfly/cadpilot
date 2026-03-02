## ADDED Requirements

### Requirement: Vertex-level wall thickness analysis
The system SHALL compute per-vertex minimum wall thickness for a given triangle mesh. For each vertex, the analyzer SHALL cast rays along the inverted vertex normal (with epsilon offset ≈ 1e-4 mm to avoid self-intersection) and compute the distance to the nearest opposing surface intersection. The result SHALL be an array of float values (one per vertex, in millimeters).

#### Scenario: Simple cylinder wall thickness
- **WHEN** a hollow cylinder mesh (OD=20mm, ID=16mm) is analyzed
- **THEN** all vertices on the inner and outer surfaces SHALL report wall thickness values between 1.8mm and 2.2mm (±10% tolerance for tessellation artifacts)

#### Scenario: Variable thickness plate
- **WHEN** a plate with one thick region (5mm) and one thin region (0.5mm) is analyzed
- **THEN** vertices in the thin region SHALL report values < 1.0mm and vertices in the thick region SHALL report values > 4.0mm

#### Scenario: No intersection found
- **WHEN** a ray cast from a vertex does not intersect any opposing surface (e.g., open mesh edge)
- **THEN** the vertex SHALL be assigned the maximum sentinel value (999.0mm), indicating "no wall detected"

### Requirement: Vertex-level overhang angle analysis
The system SHALL compute per-vertex overhang angle relative to the build direction (default: +Z axis). For each vertex, the overhang angle SHALL be calculated as the angle between the vertex normal and the build direction vector. The result SHALL be an array of float values (one per vertex, in degrees, range 0-180).

#### Scenario: Flat horizontal surface
- **WHEN** a flat surface with normal pointing up (+Z) is analyzed with build direction +Z
- **THEN** all vertices on that surface SHALL report overhang angle of 0°

#### Scenario: 45-degree overhang
- **WHEN** a surface angled at 45° from vertical is analyzed
- **THEN** vertices on that surface SHALL report overhang angle of approximately 45°

#### Scenario: Downward-facing surface (elevated)
- **WHEN** a surface with normal pointing down (-Z) is analyzed, and its Z coordinate is above the build plate (z > build_plate_tolerance, default 0.5mm)
- **THEN** vertices SHALL report overhang angle of 180° (fully unsupported)

#### Scenario: Bottom surface on build plate
- **WHEN** a surface with normal pointing down (-Z) is analyzed, and its Z coordinate is at or below build plate tolerance (z ≤ 0.5mm)
- **THEN** vertices SHALL report overhang angle of 0° (resting on build plate, no support needed)

### Requirement: Risk normalization
The system SHALL normalize analysis values to a [0,1] risk scale where 0.0 = maximum risk (thinnest wall / worst overhang) and 1.0 = no risk (thickest wall / no overhang). Normalization SHALL use configurable thresholds from the active PrintProfile.

#### Scenario: Wall thickness normalization
- **WHEN** wall thickness values are normalized with min_wall_thickness=1.0mm threshold
- **THEN** vertices with thickness ≤ min_wall_threshold SHALL map to risk 0.0, vertices with thickness ≥ 3× threshold SHALL map to risk 1.0, and intermediate values SHALL be linearly interpolated

### Requirement: Ray-casting robustness
The ray-casting implementation SHALL handle edge cases robustly:
- Ray origin SHALL be offset by epsilon (≈ 1e-4 mm) along the inverted normal to prevent self-intersection
- Non-manifold vertices (shared by disconnected face groups) SHALL be assigned the sentinel value (999.0mm)
- The system SHOULD use `pyembree` (C++ BVH accelerator) when available for 10-100× speedup; pure-Python fallback SHALL still produce correct results

#### Scenario: Self-intersection avoidance
- **WHEN** a ray is cast from a vertex on a flat surface
- **THEN** the ray SHALL NOT intersect the originating face, and SHALL correctly find the opposing surface

### Requirement: Performance constraint
The analysis SHALL complete within 10 seconds for meshes up to 50,000 vertices (with pyembree). For larger meshes, the analyzer SHALL apply quadric decimation to reduce vertex count before analysis, then interpolate results back to the original mesh via nearest-neighbor mapping (scipy cKDTree).

#### Scenario: Large mesh decimation
- **WHEN** a mesh with 200,000 vertices is submitted for analysis
- **THEN** the analyzer SHALL decimate to ≤ 50,000 vertices, analyze, and map results back within 15 seconds total
