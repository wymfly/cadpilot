# DfAM 3D 热力图 — 实施任务

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 CADPilot 添加顶点级 DfAM 分析（壁厚 + 悬垂角）和 3D 热力图可视化

**Architecture:** 后端 VertexAnalyzer 逐顶点 ray-casting → GLB 顶点颜色编码 → 前端 ShaderMaterial 渲染 + PrintReport 联动

**Tech Stack:** trimesh + scipy (KD-tree 降采样回映) + pyembree (可选加速) | Three.js ShaderMaterial | glTF COLOR_0 | React

---

## 域标签

| 标签 | 涉及模块 |
|------|---------|
| `[backend]` | vertex_analyzer, format_exporter, geometry_extractor, graph node |
| `[frontend]` | Viewer3D, ViewControls, HeatmapLegend, PrintReport |
| `[test]` | 后端单元测试, 前端类型检查 |

---

## Task 0: 接口定义（串行前置）

**Files:**
- Create: `backend/core/vertex_analyzer.py` (接口 + 数据类)
- Modify: `backend/models/printability.py` (PrintIssue 增加 region 字段)
- Modify: `frontend/src/types/printability.ts` (同步 region 字段)
- Modify: `frontend/src/types/generate.ts` (WorkflowState 增加 dfamGlbUrl)

**描述:** 定义跨模块共享的接口和数据类型，确保后续并行任务基于稳定接口工作。

**步骤:**
1. `uv add scipy`（新增依赖）
2. 创建 `backend/core/vertex_analyzer.py`，定义 `VertexAnalysisResult` dataclass（`wall_thickness: np.ndarray`, `overhang_angle: np.ndarray`, `risk_wall: np.ndarray`, `risk_overhang: np.ndarray`, `stats: dict`）和 `VertexAnalyzer` 类的接口签名（`analyze(mesh_path, build_direction, profile) → VertexAnalysisResult`）
3. 在 `PrintIssue` 模型中增加 `region: Optional[dict]`（`{center: [x,y,z], radius: float}`）
4. 前端 `printability.ts` 同步增加 `region?: { center: number[]; radius: number }`
5. 前端 `generate.ts` 的 `WorkflowState` 增加 `dfamGlbUrl: string | null`
6. 运行 `uv run pytest tests/ -q` + `npx tsc --noEmit` 确认无破坏

---

## Task 1: 顶点级壁厚分析器 `[backend]`

**Files:**
- Modify: `backend/core/vertex_analyzer.py` (实现分析逻辑)
- Create: `tests/test_vertex_analyzer.py`

**描述:** 实现 ray-casting 壁厚计算 + 悬垂角计算 + 风险归一化。

**步骤:**
1. 实现 `_compute_wall_thickness(mesh, normals)`: 逐顶点沿反向法线 ray-cast（epsilon 偏移 1e-4 避免自相交），返回 float 数组。非流形顶点标记为 999.0 sentinel。
2. 实现 `_compute_overhang_angle(normals, build_dir)`: 法线与构建方向夹角。**构建平台排除**：z ≤ build_plate_tolerance（0.5mm）且法线朝下的顶点设为 0°（贴底面无需支撑）。
3. 实现 `_normalize_risk(values, threshold, safe_multiple=3.0)`: 线性归一化到 [0,1]
4. 实现大网格降采样：`mesh.simplify_quadric_decimation(50000)` + `cKDTree` 最近邻回映
5. 编写测试：简单圆柱壁厚 ≈ 2mm、平板悬垂角 = 0°、无交射线 → 999.0 sentinel、底面贴平台悬垂角 = 0°、自相交避免验证
6. `uv run pytest tests/test_vertex_analyzer.py -v`

---

## Task 2: DfAM GLB 导出 `[backend]`

**Files:**
- Modify: `backend/core/format_exporter.py` (新增 export_dfam_glb 方法)
- Create: `tests/test_dfam_export.py`

**描述:** 将顶点分析结果编码为 GLB 顶点颜色属性。

**步骤:**
1. 实现 `export_dfam_glb(mesh, analysis_result, output_path)`:
   - 创建两个命名 mesh：`mesh.name = "wall_thickness"` 和 `mesh.name = "overhang"`
   - 设置 `COLOR_0` vertex attribute（R=risk_value, G=0, B=0, A=255, uint8）
   - 设置 **per-mesh extras**（非 scene 级）: `{analysis_type, threshold, min_value, max_value, vertices_at_risk_count, vertices_at_risk_percent}`
   - 使用 trimesh `export(file_type='glb')` with vertex_colors
2. 编写测试：导出后重新加载，验证：顶点颜色数组长度 = 顶点数、两个 mesh 可通过 name 区分、per-mesh extras 存在
3. `uv run pytest tests/test_dfam_export.py -v`

---

## Task 3: 管道集成 — analyze_dfam 节点 `[backend]`

**Files:**
- Create: `backend/graph/nodes/dfam.py` (analyze_dfam_node)
- Modify: `backend/graph/builder.py` (添加节点到 DAG)
- Modify: `backend/graph/state.py` (增加 dfam 相关 state keys)
- Modify: `frontend/src/components/PipelineDAG/topology.ts` (添加 analyze_dfam 节点)

**描述:** 将 DfAM 分析集成到 LangGraph 管道中。

**步骤:**
1. 创建 `analyze_dfam_node`：**内部 try-except** 包裹全部逻辑（加载 mesh → `VertexAnalyzer.analyze()` → `export_dfam_glb()`），异常时返回 `{dfam_glb_url: None, dfam_stats: None, _reasoning: {error: str(e)}}`。正常时返回 `{dfam_glb_url, dfam_stats}`。使用 `build_output_url()` 生成 URL。
2. 装饰 `@timed_node("analyze_dfam")`
3. 在 `builder.py` 中，text/drawing 工作流的 `convert_preview` 之后、`check_printability` 之前插入 `analyze_dfam`。**Organic 工作流不包含此节点**。
4. `CadJobState` 增加 `dfam_glb_url: str | None`, `dfam_stats: dict | None`
5. `topology.ts` 添加 `analyze_dfam` 节点（group: 'postprocess'）和对应 edge
6. 前端 `node.completed` 事件已通过 M3 的 `_eventType` 机制自动处理，仅需在 `WorkflowState` 更新逻辑中提取 `dfamGlbUrl`（从 `outputs_summary` 或专用 business event）
7. 运行全量测试确认管道无破坏

---

## Task 4: Three.js DfAM 热力图渲染 `[frontend]`

**Files:**
- Create: `frontend/src/components/Viewer3D/DfamShader.ts` (ShaderMaterial 定义)
- Create: `frontend/src/components/Viewer3D/HeatmapLegend.tsx` (颜色条组件)
- Modify: `frontend/src/components/Viewer3D/index.tsx` (DfAM 模式切换逻辑)
- Modify: `frontend/src/components/Viewer3D/ViewControls.tsx` (DfAM 按钮)

**描述:** 前端热力图渲染 + 视图切换 + 颜色条。

**步骤:**
1. 创建 `DfamShader.ts`：自定义 vertex/fragment shader，R 通道 → green→yellow→red 渐变
2. 创建 `HeatmapLegend.tsx`：垂直颜色条 + 刻度标签，props: `{type: 'wall_thickness'|'overhang', min, max, unit}`
3. 修改 `Viewer3D/index.tsx`：
   - 新增 `dfamMode` state ('normal' | 'wall_thickness' | 'overhang')
   - 当 dfamMode 切换时，fetch `dfamGlbUrl`，加载 DfAM GLB，应用 ShaderMaterial
   - 切回 normal 时恢复原始 mesh
4. 修改 `ViewControls.tsx`：添加 DfAM 模式切换按钮（3 个 radio 选项）
5. `npx tsc --noEmit` 确认类型安全

---

## Task 5: PrintReport ↔ Viewer3D 联动 `[frontend]`

**Files:**
- Modify: `frontend/src/components/PrintReport/IssueList.tsx` (点击事件 + 定位图标)
- Modify: `frontend/src/components/Viewer3D/index.tsx` (暴露 focusOnRegion 方法)
- Modify: `frontend/src/pages/Generate/index.tsx` (连接报告和 viewer)

**描述:** issue 点击 → 3D 相机飞行到问题区域。

**步骤:**
1. `IssueList.tsx`：有 `region` 的 issue 行显示定位图标，点击调用 `onLocateIssue(region)`
2. `Viewer3D/index.tsx`：通过 `useImperativeHandle` 暴露 `focusOnRegion({center, radius})` 方法，内部用 `camera.lookAt` + TWEEN 动画
3. `Generate/index.tsx`：用 ref 连接 PrintReport 的 onLocateIssue 到 Viewer3D 的 focusOnRegion
4. `npx tsc --noEmit` + 手动验证联动效果

---

## Task 6: PrintabilityChecker 增强 — 利用顶点级数据 `[backend]`

**Files:**
- Modify: `backend/core/printability.py` (使用顶点分析结果填充 region)
- Modify: `backend/core/geometry_extractor.py` (调用 vertex_analyzer)
- Modify: `tests/test_printability.py`

**描述:** 替代当前的全局估算，用顶点级数据生成带位置信息的 issue。

**步骤:**
1. `geometry_extractor.py`：当 mesh 可用时，调用 `VertexAnalyzer` 填充 `min_wall_thickness` 和 `max_overhang_angle`
2. `printability.py`：检查结果中为超限 issue 附加 `region`（取超限顶点的质心和包围球）
3. 更新测试验证 issue 包含 region 字段
4. `uv run pytest tests/test_printability.py -v`

---

## Task 7: 集成验证（串行收尾）

**Files:** 全部

**描述:** 端到端验证 + 全量测试。

**步骤:**
1. `uv run pytest tests/ -v` — 全部通过
2. `cd frontend && npx tsc --noEmit` — 无类型错误
3. `cd frontend && npm run build` — 构建成功
4. 手动 E2E 验证：提交一个文本/图纸 Job → 查看 DAG 面板 `analyze_dfam` 节点状态 → 切换 DfAM 热力图 → 点击 issue 联动
5. 提交代码

---

## 并行性分析

| Task | 可并行 | 依赖 | 预期修改文件 |
|------|--------|------|-------------|
| T0 | 否（串行前置） | 无 | vertex_analyzer.py (接口), printability.py, printability.ts, generate.ts |
| T1 | ✅ | T0 | vertex_analyzer.py (实现), test_vertex_analyzer.py |
| T2 | ✅ | T0 | format_exporter.py, test_dfam_export.py |
| T3 | ✅ | T0 | dfam.py, builder.py, state.py, topology.ts |
| T4 | ✅ | T0 | DfamShader.ts, HeatmapLegend.tsx, Viewer3D/index.tsx, ViewControls.tsx |
| T5 | 否 | T4 | IssueList.tsx, Viewer3D/index.tsx, Generate/index.tsx |
| T6 | 否 | T1 | printability.py, geometry_extractor.py |
| T7 | 否（串行收尾） | 全部 | 无新文件 |

**文件交叉矩阵:**
- T1 ↔ T2: 无交叉（vertex_analyzer.py 实现 vs format_exporter.py）
- T1 ↔ T3: 无交叉（vertex_analyzer 实现 vs graph node + builder）
- T1 ↔ T4: 无交叉（后端 vs 前端）
- T2 ↔ T3: 无交叉（export 函数 vs graph node）
- T2 ↔ T4: 无交叉（后端 vs 前端）
- T3 ↔ T4: T3 修改 topology.ts, T4 修改 Viewer3D — **无交叉**

**结论: T1/T2/T3/T4 可完全并行执行。**
