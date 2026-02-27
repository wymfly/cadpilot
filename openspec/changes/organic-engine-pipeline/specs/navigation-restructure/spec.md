## ADDED Requirements

### Requirement: Two-level sidebar menu
The system SHALL restructure the sidebar navigation into a two-level menu with "精密建模" as a submenu group containing existing mechanical pipeline pages, and "创意雕塑" as a standalone entry.

#### Scenario: Menu structure
- **WHEN** user views the sidebar
- **THEN** menu shows: 首页, 精密建模 (expandable: 文本/图纸生成, 参数化模板, 工程标准, 评测基准), 创意雕塑, 设置

#### Scenario: Submenu expansion
- **WHEN** user clicks "精密建模" menu group
- **THEN** submenu expands showing 4 child items; clicking any child navigates to the corresponding page

#### Scenario: Active state highlighting
- **WHEN** user is on `/templates` page
- **THEN** "精密建模" group is expanded and "参数化模板" item is highlighted

#### Scenario: Sub-route highlighting
- **WHEN** user is on `/benchmark/run` (sub-route of benchmark)
- **THEN** "评测基准" menu item under "精密建模" is highlighted

### Requirement: Homepage dual-entry layout
The system SHALL redesign the homepage with two primary entry cards (精密建模 / 创意雕塑) and three secondary cards (模板 / 标准 / 评测).

#### Scenario: Primary cards navigation
- **WHEN** user clicks "精密建模" primary card
- **THEN** user navigates to `/generate`

#### Scenario: Organic entry card
- **WHEN** user clicks "创意雕塑" primary card
- **THEN** user navigates to `/generate/organic`

#### Scenario: Secondary cards
- **WHEN** user clicks "参数化模板" secondary card
- **THEN** user navigates to `/templates`

### Requirement: Header tagline update
The system SHALL update the header tagline from "AI 驱动的 2D → 3D CAD 生成平台" to "AI 驱动的 3D 模型生成平台".

#### Scenario: Updated tagline displayed
- **WHEN** user views any page
- **THEN** header shows "AI 驱动的 3D 模型生成平台"
