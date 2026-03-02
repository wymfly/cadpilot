## ADDED Requirements

### Requirement: DfAM view mode toggle
The Viewer3D toolbar SHALL include a DfAM view selector with three modes: "Normal" (default), "Wall Thickness", and "Overhang". Switching modes SHALL load the DfAM GLB (lazy, on first activation) and apply the corresponding vertex color rendering.

#### Scenario: First activation of DfAM view
- **WHEN** user clicks "Wall Thickness" for the first time on a completed job
- **THEN** the system SHALL fetch `model_dfam.glb`, display a loading indicator, then render the wall thickness heatmap

#### Scenario: Toggle back to normal view
- **WHEN** user switches from DfAM view back to Normal
- **THEN** the viewer SHALL display the original model with standard material (no vertex colors)

#### Scenario: DfAM unavailable
- **WHEN** the job has no DfAM analysis data (e.g., analysis failed or was skipped)
- **THEN** the DfAM buttons SHALL be disabled with tooltip "DfAM 分析不可用"

### Requirement: Heatmap shader rendering
The system SHALL render DfAM heatmaps using a custom ShaderMaterial that maps the vertex color R channel to a green→yellow→red gradient. The colormap SHALL be: R=0.0 → RGB(220,38,38) red, R=0.5 → RGB(234,179,8) yellow, R=1.0 → RGB(34,197,94) green.

#### Scenario: Visual accuracy of gradient
- **WHEN** a model with smoothly varying wall thickness is displayed in DfAM mode
- **THEN** the heatmap SHALL show a smooth color gradient from red (thin) through yellow to green (thick), without banding artifacts

#### Scenario: Shader fallback (no WebGL2)
- **WHEN** the browser does not support custom ShaderMaterial
- **THEN** the system SHALL fall back to MeshBasicMaterial with vertexColors, displaying red-intensity only (deep red = high risk, light red = low risk), and show a tooltip "颜色映射精度降低"

### Requirement: Color bar legend
A vertical color bar legend SHALL be displayed alongside the 3D viewer when DfAM mode is active. The legend SHALL show the color gradient with labeled tick marks indicating actual measurement values (e.g., "0.5mm", "1.0mm", "2.0mm" for wall thickness; "0°", "45°", "90°" for overhang).

#### Scenario: Legend updates per analysis type
- **WHEN** user switches from wall thickness to overhang view
- **THEN** the legend SHALL update to show angle values (degrees) instead of thickness values (mm)

### Requirement: PrintReport issue click-to-locate
When a PrintIssue has a `region` field (center + radius), clicking the issue in PrintReport SHALL animate the 3D camera to focus on that region. The camera SHALL smoothly orbit to face the region center at an appropriate distance.

#### Scenario: Click issue with region data
- **WHEN** user clicks a "壁厚不合格" issue that has region `{center: [10, 5, 3], radius: 8}`
- **THEN** the camera SHALL animate over 0.5s to look at point [10, 5, 3] from a distance of approximately 2× the radius

#### Scenario: Click issue without region data
- **WHEN** user clicks an issue that has no `region` field (e.g., build volume exceeded)
- **THEN** no camera movement SHALL occur (issue row shows no "locate" icon)

### Requirement: Risk statistics summary
When DfAM mode is active, the Viewer3D SHALL display a compact statistics overlay showing: percentage of vertices at risk, most critical area label, and threshold used.

#### Scenario: Statistics display
- **WHEN** DfAM wall thickness view is active
- **THEN** an overlay SHALL show e.g., "12.3% 顶点低于阈值 (1.0mm)" and the total vertex count
