## Why

cad3dify 当前的机械引擎（CadQuery 代码生成）只能处理由标准几何体构成的零件。面对高尔夫球头、人体工学手柄、艺术雕塑等自由曲面零件时，代码生成路径彻底失效。为覆盖 3D 打印业务的全场景，需要引入独立的「有机引擎」管道，通过 AI 3D 生成 + 计算几何后处理输出可打印工业件。

## What Changes

- 新增完全独立的有机管道后端（`/api/generate/organic`），不侵入现有机械管道
- 集成 Tripo3D（主）+ Hunyuan3D（备）云端 3D 生成 API，支持 Text-to-3D 和 Image-to-3D
- 新增网格后处理管线：PyMeshLab 修复 → trimesh 缩放 → manifold3d 布尔切削（平底、安装孔）
- 新增独立前端页面 `/generate/organic`，含创意输入、工程约束表单、质量选择、进度展示
- 重构侧边栏为二级菜单：「精密建模」子组（现有页面）+ 「创意雕塑」独立入口
- 首页改版为双入口卡片布局（精密建模 / 创意雕塑）

## Capabilities

### New Capabilities

- `organic-pipeline`: 有机管道核心 — OrganicSpec 构建、MeshProvider 抽象、AI 3D 生成、网格后处理（修复/缩放/布尔切削/校验）、SSE 流式进度
- `organic-frontend`: 有机管道前端 — 创意输入组件、工程约束表单、质量选择器、进度展示、网格统计、独立页面和路由
- `navigation-restructure`: 导航重构 — 侧边栏二级菜单、首页双入口卡片、Header 更新

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

- **后端新增模块**: `api/organic.py`, `core/organic_spec_builder.py`, `core/mesh_post_processor.py`, `models/organic.py`, `infra/mesh_providers/`
- **前端新增页面**: `pages/OrganicGenerate/`（7 个组件）, `contexts/OrganicWorkflowContext.tsx`, `types/organic.ts`
- **前端修改**: `MainLayout.tsx`（二级菜单）, `Home/index.tsx`（双入口）, `App.tsx`（路由 + Provider）
- **新增依赖**: `manifold3d>=3.0.0`, `pymeshlab>=2025.0`
- **新增配置**: `TRIPO3D_API_KEY`, `HUNYUAN3D_API_KEY`
- **不影响**: 现有机械管道代码、Generate 页面、PipelineConfig 体系
