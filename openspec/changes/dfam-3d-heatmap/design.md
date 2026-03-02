## Context

CADPilot 当前的可打印性检查 (`PrintabilityChecker`) 输出全局级判断：整体最小壁厚、最大悬垂角等标量值。`GeometryExtractor` 对 STEP 文件仅提取包围盒和体积，对 Mesh 文件可估算最大悬垂角但无顶点级定位。用户收到"壁厚不合格"后无法知道**哪里**薄、薄多少。

M3 已完成白盒化 UI（DAG 看板 + Reasoning Trace），为 DfAM 分析提供了管道可观测基础。Three.js Viewer3D 组件已支持 GLB 加载和 OrbitControls，但仅使用 `meshStandardMaterial`（单色），无顶点颜色渲染能力。

**约束**：
- trimesh + numpy 已在依赖中；**scipy 需新增**（`uv add scipy`，用于 cKDTree 降采样回映）
- `pyembree` 为可选加速依赖（C++ 扩展），缺失时 trimesh 退化为纯 Python ray-casting（性能下降 10-100×），生产环境建议安装
- 顶点分析是 CPU 密集型操作，需通过 `asyncio.to_thread` 异步化
- GLB 顶点颜色使用 `COLOR_0` accessor（glTF 2.0 标准）
- Three.js GLTFLoader 自动解析 `COLOR_0`，但需要材质支持 `vertexColors: true`
- Organic 工作流（HITL 有机建模）跳过 DfAM 分析（mesh 由用户提供而非管道生成）

## Goals / Non-Goals

**Goals:**
- 用户在 Viewer3D 中一键切换 DfAM 热力图（壁厚/悬垂角两种模式）
- 热力图颜色直观表达风险等级：绿色（安全）→ 黄色（临界）→ 红色（超限）
- PrintReport issue 点击后 3D 视图旋转到对应问题区域
- 分析结果嵌入 GLB 文件（顶点颜色），支持离线查看

**Non-Goals:**
- 不做切片模拟或支撑结构生成（属于切片器集成范畴）
- 不做实时参数修改后的动态热力图更新（属于参数化编辑范畴）
- 不做多种打印方向的对比分析（V1 仅支持单一方向）
- 不做 GPU 加速的 SDF 计算（CPU 版本满足当前模型规模）

## Decisions

### D1: 壁厚算法 — Ray-casting（BVH 加速）+ KD-tree 降采样回映

**选择**：从每个顶点沿法线反向发射射线，与对面表面求交，取最近交点距离作为壁厚。

**技术细节**：
- **Ray-casting**：由 trimesh `ray.intersects_location()` 实现，底层使用 BVH（Bounding Volume Hierarchy）加速（pyembree 时）或 rtree 索引（无 pyembree 时）
- **KD-tree**：`scipy.spatial.cKDTree` 仅用于**降采样结果回映**——将分析结果从简化网格映射回原始网格的最近邻插值，不参与 ray-casting 计算
- **鲁棒性**：射线需沿法线反向偏移 epsilon（≈1e-4 mm）避免自相交；非流形边缘处顶点标记为 sentinel（999.0mm）

**备选**：
- Signed Distance Field (SDF)：精度高但需体素化，内存消耗大（100mm³ × 0.1mm 分辨率 = 10⁹ 体素）
- Medial Axis Transform：理论最优但实现复杂，trimesh 无内置支持
- 球体拟合 / 射线锥：精度更好但实现复杂度高，MVP 阶段不需要

**理由**：trimesh 内置 ray-casting + BVH 加速，对典型 CAD 模型（10K-100K 面）单次分析 < 5s（有 pyembree 时）。无 pyembree 退化至 < 30s，仍在可接受范围。

### D2: 顶点颜色编码 — 单独 DfAM GLB（非修改原始 GLB）

**选择**：生成独立的 `model_dfam.glb` 文件，包含壁厚和悬垂角两组顶点颜色数据。原始 `model.glb` 保持不变。

**备选**：通过 buffer 属性扩展原始 GLB

**理由**：分离关注点，原始模型不受影响。DfAM GLB 可懒加载（用户点击 DfAM 按钮时才请求）。

**双 mesh 区分方案**：GLB 内包含两个命名 mesh：`mesh.name = "wall_thickness"` 和 `mesh.name = "overhang"`。每个 mesh 各自携带独立的 `extras` 元数据（analysis_type、threshold、min/max 值等），前端通过 `mesh.name` 精确查找。

**文件大小**：双 mesh 会复制几何数据（顶点 + 索引），典型模型 GLB 从 ~3MB 增至 ~7MB。可接受（懒加载 + HTTP 压缩）。未来可优化为共享几何的自定义属性方案。

**URL 生成**：使用已有的 `build_output_url()` 辅助函数生成 `dfam_glb_url`，不硬编码路径。

### D3: 颜色映射 — 归一化到 [0,1] + GPU colormap

**选择**：后端将壁厚/悬垂值归一化到 [0,1]（0=最差，1=最安全），编码为 GLB `COLOR_0` 的 R 通道。前端 ShaderMaterial 在 fragment shader 中将 R 值映射为 green→yellow→red 渐变。

**理由**：单通道编码节省空间，colormap 在 GPU 端实现更灵活（可切换配色方案）。

**Fallback**：若浏览器不支持 WebGL2 自定义 shader，降级为 `MeshBasicMaterial` + `vertexColors: true`。由于 R-only 编码无法在 BasicMaterial 中产生绿色，降级后仅显示红色深浅（深红=高风险，浅红=低风险），并在 UI 中提示"颜色映射精度降低"。

**精度说明**：8-bit COLOR_0 足够 MVP 可视化。前端 tooltip 显示近似工程值时，可通过 mesh extras 的 min/max 范围反推（`value = min + risk * (max - min)`）。

### D4: 管道集成 — postprocess 阶段新增 DfAM 分析步骤

**选择**：在 `convert_preview` 节点之后、`check_printability` 之前插入 `analyze_dfam` 节点。此节点加载 mesh，运行顶点分析，生成 DfAM GLB。

**理由**：此时 mesh 已经过后处理（repair/scale/boolean），是最终几何形状。分析结果同时供 `check_printability` 使用（替代当前的全局估算）。

**数据流**：`analyze_dfam` 将 `VertexAnalysisResult` 的统计摘要写入 state（`dfam_stats`），`check_printability` 读取 `dfam_stats` 中的 `min_wall_thickness`、`max_overhang_angle` 等字段，替代 `GeometryExtractor` 的粗略估算。

**故障处理**：`analyze_dfam` 节点**内部 try-except** 捕获所有异常（mesh 加载失败、trimesh 错误等），返回 `{dfam_glb_url: None, dfam_stats: None, _reasoning: {error: ...}}`。`@timed_node` 看到正常返回（非异常），派发 `node.completed`（而非 `node.failed`）。`check_printability` 检测到 `dfam_stats is None` 时回退到全局估算。

**Organic 路径**：`builder.py` 中 organic 工作流的图定义不包含 `analyze_dfam` 节点（organic mesh 由用户上传，不需要 DfAM 分析）。

### D5: 报告联动 — 基于 issue bounding box 的相机动画

**选择**：每个 `PrintIssue` 增加可选 `region` 字段（`{center: [x,y,z], radius: number}`），表示问题区域的空间位置。前端点击 issue 时，使用 Three.js 相机动画平滑旋转到该区域。

**理由**：不需要精确的顶点级选择（开销大），区域级定位已满足工程师需求。

## Risks / Trade-offs

**[性能] 大模型分析耗时** → 对 > 50K 顶点的模型，ray-casting 可能超过 10s。Mitigation: 添加顶点降采样（`mesh.simplify_quadric_decimation(target=50000)`），分析降采样后的网格，结果通过最近邻插值映射回原始网格。

**[精度] Ray-casting 壁厚在复杂几何中可能不准确** → 薄壁+弯曲表面时射线可能错过对面。Mitigation: 对每个顶点发射多条射线（法线 ± 15°锥形扇出），取最小值。

**[兼容性] 部分浏览器不支持 WebGL2 custom shaders** → Mitigation: 降级到 MeshBasicMaterial + vertexColors（红色深浅显示），并提示用户颜色精度降低。

**[文件大小] DfAM GLB 因双 mesh 约为原始的 2 倍** → 典型 3MB 模型生成 ~7MB DfAM GLB。Mitigation: 懒加载 + HTTP gzip 压缩。未来可优化为共享几何 + 自定义属性方案。

**[区域定位精度] 单质心+包围球对多簇分散缺陷不够精确** → MVP 版本取所有超限顶点的质心和包围球。已知限制，后续可升级为 DBSCAN 聚类生成多个 region。
