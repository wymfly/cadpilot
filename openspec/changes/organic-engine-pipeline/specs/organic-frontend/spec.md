## ADDED Requirements

### Requirement: Organic generation page
The system SHALL provide an independent page at `/generate/organic` for organic 3D model generation.

#### Scenario: Page renders with all sections
- **WHEN** user navigates to `/generate/organic`
- **THEN** page displays: creative input area, engineering constraint form, quality selector, and 3D viewer

### Requirement: Text and image input modes
The system SHALL support two input modes via tab switching: text prompt input and reference image upload.

#### Scenario: Text input submission
- **WHEN** user types a prompt in the text tab and clicks "生成"
- **THEN** system calls `POST /api/generate/organic` with the prompt and configured constraints

#### Scenario: Image input submission
- **WHEN** user uploads an image in the image tab and clicks "生成"
- **THEN** system calls `POST /api/generate/organic/upload` with the image file

#### Scenario: Image upload validation
- **WHEN** user attempts to upload a file larger than 10MB or with unsupported format
- **THEN** frontend shows inline error message before submission, preventing the upload

### Requirement: Engineering constraint form
The system SHALL provide a form for configuring bounding box dimensions and engineering cut interfaces (flat bottom, holes, slots) with dynamic add/remove.

#### Scenario: Add engineering cut
- **WHEN** user clicks "+ 添加安装孔"
- **THEN** a new engineering cut entry appears with fields for type, diameter, depth, and direction

#### Scenario: Remove engineering cut
- **WHEN** user removes an engineering cut entry
- **THEN** the entry is removed from the constraint list

#### Scenario: Bounding box input
- **WHEN** user enters X=80, Y=80, Z=60 in the bounding box fields
- **THEN** constraints include `bounding_box: [80, 80, 60]`

### Requirement: Quality mode selector
The system SHALL provide a radio group for selecting quality mode (draft/standard/high) and provider preference (auto/tripo3d/hunyuan3d).

#### Scenario: Quality mode selection
- **WHEN** user selects "高质量" quality mode
- **THEN** request includes `quality_mode: "high"`

### Requirement: Organic workflow progress display
The system SHALL display a 4-step progress indicator (分析 → 生成 → 后处理 → 完成) with real-time SSE status updates.

#### Scenario: Progress updates during generation
- **WHEN** backend sends SSE event `{"status": "generating", "progress": 0.5}`
- **THEN** progress bar shows 50% at the "生成" step with the message

#### Scenario: Error display
- **WHEN** backend sends SSE event `{"status": "failed", "message": "..."}`
- **THEN** progress indicator shows error state with the error message

### Requirement: 3D model preview
The system SHALL display the generated 3D model using the existing Viewer3D component (Three.js GLB loader).

#### Scenario: Model preview on completion
- **WHEN** generation completes with `model_url`
- **THEN** Viewer3D renders the GLB model with orbit controls

### Requirement: Mesh statistics display
The system SHALL display mesh quality statistics (vertex count, face count, watertight status, volume, bounding box) after generation completes.

#### Scenario: Stats card shown on completion
- **WHEN** generation completes with `mesh_stats`
- **THEN** MeshStatsCard displays all statistics with watertight status highlighted

### Requirement: Download buttons
The system SHALL provide download buttons for STL and 3MF formats after generation completes.

#### Scenario: Download STL
- **WHEN** user clicks "STL" download button
- **THEN** browser downloads the STL file from `stl_url`

### Requirement: Organic workflow state persistence
The system SHALL persist organic workflow state (phase, model URL, mesh stats) across page navigation using React Context, matching the mechanical pipeline's behavior.

#### Scenario: State preserved across navigation
- **WHEN** user navigates away from `/generate/organic` and returns
- **THEN** all state (progress, 3D model, mesh stats, download URLs) is preserved

### Requirement: Reset functionality
The system SHALL provide a "重新开始" button to reset the organic workflow to idle state.

#### Scenario: Reset clears all state
- **WHEN** user clicks "重新开始"
- **THEN** workflow returns to idle, model preview is cleared, and all forms are reset
