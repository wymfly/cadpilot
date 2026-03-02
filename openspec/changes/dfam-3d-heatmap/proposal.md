## Why

当前 PrintabilityChecker 仅提供全局级可打印性判断（整体壁厚是否合格、最大悬垂角是否超限），用户无法直观看到**问题出在模型的哪个位置**。这是工业级 CAD 平台与 demo 工具的核心差距——工程师需要在提交打印前精确定位薄壁区域和悬垂风险区域，而非仅收到一条"壁厚不合格"的文字提示。

## What Changes

- 新增**顶点级壁厚分析器**：基于 Ray-casting / KD-tree 逐顶点计算到最近相对表面的距离
- 新增**顶点级悬垂角分析器**：计算每个面法线与打印方向的夹角，映射到顶点
- 扩展 **GLB 导出**：在 GLB 文件中嵌入 `COLOR_0` 顶点属性，编码风险值（绿→黄→红）
- 新增 **DfAM 热力图渲染**：Three.js 自定义 ShaderMaterial，根据顶点颜色渲染壁厚/悬垂热力图
- 扩展 **Viewer3D**：工具栏增加 DfAM 视图切换（普通/壁厚/悬垂），附带颜色条图例
- 增强 **PrintReport ↔ Viewer3D 联动**：点击 issue 项 → 3D 视图旋转到对应问题区域并高亮

## Capabilities

### New Capabilities
- `vertex-analysis`: 顶点级 DfAM 分析引擎（壁厚 + 悬垂角逐顶点计算，输出顶点风险值数组）
- `heatmap-glb-export`: GLB 热力图导出（将顶点级分析结果编码为 GLB COLOR_0 属性）
- `dfam-3d-visualization`: 前端 DfAM 热力图渲染（ShaderMaterial + 颜色条 + 视图切换 + 报告联动）

### Modified Capabilities
- `graph-event-streaming`: DfAM 分析节点加入管道后需 dispatch 对应 `node.started/completed` 事件

## Impact

- **后端新增模块**：`backend/core/vertex_analyzer.py`（CPU 密集型，需 asyncio.to_thread）
- **后端修改**：`backend/core/format_exporter.py`（GLB 导出增加顶点颜色）、`backend/core/geometry_extractor.py`（调用 vertex_analyzer）、`backend/graph/nodes/postprocess.py`（集成 DfAM 分析节点）
- **前端新增**：DfAM shader 材质、HeatmapLegend 颜色条组件
- **前端修改**：`Viewer3D/index.tsx`（视图模式切换）、`ViewControls.tsx`（DfAM 按钮）、`PrintReport/IssueList.tsx`（点击联动）
- **依赖**：trimesh（已有）、numpy（已有）、scipy（KD-tree，需确认是否已安装）
- **API**：现有 Job 管道自动集成，无需新增端点
