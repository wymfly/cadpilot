## ADDED Requirements

### Requirement: Slice to gcode node registration
`slice_to_gcode` 节点 SHALL 注册为可选策略化节点，requires=[["final_mesh", "scaled_mesh", "watertight_mesh"]]（OR 依赖），produces=["gcode_bundle"]，input_types=["organic"]。

#### Scenario: Node registered with slicer strategies
- **WHEN** NodeRegistry 完成发现
- **THEN** `registry.get("slice_to_gcode")` 返回 descriptor，strategies 包含 "prusaslicer" 和 "orcaslicer"，default_strategy="prusaslicer"

### Requirement: PrusaSlicer CLI integration
PrusaSlicerStrategy SHALL 通过 CLI 调用 PrusaSlicer 进行切片，使用纯参数模式（无需配置文件）。

#### Scenario: Basic slicing
- **WHEN** 提供 STL 网格和默认参数
- **THEN** 执行 `prusa-slicer --export-gcode --layer-height 0.2 --fill-density 20% ...` 生成 G-code 文件

#### Scenario: Custom parameters
- **WHEN** config 指定 layer_height=0.1, fill_density=50, support_material=True, nozzle_diameter=0.6, filament_type="PETG"
- **THEN** CLI 参数正确映射，包括 `--nozzle-diameter 0.6` 和 `--filament-type PETG`（所有硬件参数必须透传，避免挤出不匹配）

#### Scenario: Configurable CLI path
- **WHEN** config.prusaslicer_path 已配置
- **THEN** 使用该路径调用 CLI，否则通过 `shutil.which("prusa-slicer")` 自动检测

#### Scenario: PrusaSlicer not installed
- **WHEN** `shutil.which("prusa-slicer")` 返回 None 且 config.prusaslicer_path 未配置
- **THEN** check_available() 返回 False，auto 模式 fallback 到 OrcaSlicer

#### Scenario: CLI timeout triggers fallback
- **WHEN** PrusaSlicer 进程执行超过 config.timeout 秒（默认 120s）
- **THEN** 终止进程，auto 模式 fallback 到 fallback_chain 中下一个策略

#### Scenario: CLI runtime error triggers fallback
- **WHEN** PrusaSlicer 进程退出码非 0
- **THEN** auto 模式 fallback 到下一个策略，非 auto 模式报错

### Requirement: OrcaSlicer CLI integration
OrcaSlicerStrategy SHALL 作为备选切片策略，CLI 参数与 PrusaSlicer 存在差异需适配。

#### Scenario: OrcaSlicer fallback
- **WHEN** PrusaSlicer 不可用，OrcaSlicer 已安装
- **THEN** 使用 OrcaSlicer CLI 执行切片

#### Scenario: OrcaSlicer CLI path detection
- **WHEN** config.orcaslicer_path 未配置
- **THEN** 通过 `shutil.which("orca-slicer")` 自动检测

#### Scenario: OrcaSlicer parameter mapping
- **WHEN** fill_density=20（百分比整数）
- **THEN** 映射为 OrcaSlicer 格式（注意 OrcaSlicer 与 PrusaSlicer 的参数格式差异，如 fill_density 不带百分号）

### Requirement: G-code metadata parsing
切片完成后 SHALL 解析 G-code 文件提取元数据。

#### Scenario: Parse gcode metadata
- **WHEN** G-code 文件生成成功
- **THEN** 提取层数、G1 指令数、耗材用量（mm/g）、预估打印时间，存入 asset metadata

#### Scenario: Gcode parse failure non-fatal
- **WHEN** G-code 文件生成成功但元数据解析失败（格式异常）
- **THEN** gcode_bundle 仍然产出（G-code 文件可用），metadata 为空 dict，记录解析警告

#### Scenario: Slicer-specific metadata format
- **WHEN** 不同切片器（PrusaSlicer/OrcaSlicer）生成的 G-code 注释格式不同
- **THEN** gcode_parser 应支持多种注释模式（如 PrusaSlicer 的 `; estimated printing time` vs OrcaSlicer 的 `; total estimated time`），优先匹配已知模式，未匹配时返回空 dict

#### Scenario: All slicer strategies fail
- **WHEN** PrusaSlicer 和 OrcaSlicer 均失败（不可用、超时或运行时错误）
- **THEN** 节点报错，job 状态标记为 failed，不产出 gcode_bundle

### Requirement: Best mesh selection
节点 SHALL 从 OR 依赖列表中选择最佳可用网格。

#### Scenario: Prefer final_mesh
- **WHEN** final_mesh 和 scaled_mesh 都可用
- **THEN** 优先使用 final_mesh

#### Scenario: Fallback to watertight_mesh
- **WHEN** 仅 watertight_mesh 可用
- **THEN** 使用 watertight_mesh

#### Scenario: No mesh available
- **WHEN** 所有 mesh 资产均不可用
- **THEN** 设置 `slice_status=skipped_no_mesh`，不产出 gcode_bundle

### Requirement: Mesh format conversion before slicing
切片器 SHALL 接受 STL 格式输入，如果源网格非 STL 则先转换。

#### Scenario: GLB input auto-converted
- **WHEN** 最佳可用网格为 GLB 格式
- **THEN** 先调用 convert_mesh 转为 STL，再送入切片器
