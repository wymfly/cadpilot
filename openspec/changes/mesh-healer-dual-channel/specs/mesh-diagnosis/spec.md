## ADDED Requirements

### Requirement: Mesh diagnosis function
系统 MUST 提供 `diagnose(mesh)` 函数，分析 trimesh.Trimesh 对象的拓扑缺陷，返回 `MeshDiagnosis` 数据结构。

#### Scenario: Clean mesh diagnosed
- **WHEN** 输入 mesh is_watertight=True 且 is_oriented=True
- **THEN** 返回 level="clean"，issues 为空列表

#### Scenario: Mild defects diagnosed
- **WHEN** 输入 mesh 有 normals 或 winding 问题，但无孔洞或非流形
- **THEN** 返回 level="mild"，issues 包含具体问题描述

#### Scenario: Moderate defects diagnosed
- **WHEN** 输入 mesh 有孔洞或非流形边
- **THEN** 返回 level="moderate"，issues 包含孔洞数量或非流形边数量

#### Scenario: Severe defects diagnosed
- **WHEN** 输入 mesh 有自相交或大面积面缺失（missing_face_ratio > threshold）
- **THEN** 返回 level="severe"，issues 包含自相交区域或缺失面比例

### Requirement: MeshDiagnosis data structure
MeshDiagnosis MUST 包含 `level`（Literal["clean", "mild", "moderate", "severe"]）和 `issues`（list[str]）两个字段。

#### Scenario: Level values are exhaustive
- **WHEN** 对任意 mesh 调用 diagnose()
- **THEN** 返回的 level 值必为 "clean"、"mild"、"moderate"、"severe" 之一

### Requirement: Repair validation function
系统 MUST 提供 `validate_repair(mesh)` 函数，检查修复后的 mesh 是否达到水密标准。

#### Scenario: Watertight mesh passes validation
- **WHEN** mesh is_watertight=True 且 volume > 0 且无退化面
- **THEN** 返回 True

#### Scenario: Non-watertight mesh fails validation
- **WHEN** mesh is_watertight=False
- **THEN** 返回 False

#### Scenario: Zero-volume mesh fails validation
- **WHEN** mesh volume <= 0
- **THEN** 返回 False
