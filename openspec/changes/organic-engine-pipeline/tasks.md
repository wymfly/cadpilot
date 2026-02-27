## 1. 依赖与配置

- [ ] 1.1 在 pyproject.toml 中添加 `manifold3d>=3.0.0` 和 `pymeshlab>=2025.0` 依赖，运行 `uv sync` 验证安装
- [ ] 1.2 在 `.env.sample` 和 `backend/config.py` 中添加 `TRIPO3D_API_KEY`、`HUNYUAN3D_API_KEY`、`ORGANIC_DEFAULT_PROVIDER` 配置项

## 2. 后端数据模型

- [ ] 2.1 创建 `backend/models/organic.py`：EngineeringCut、OrganicConstraints、OrganicGenerateRequest、OrganicSpec、MeshStats、OrganicJobResult 全部 Pydantic 模型
- [ ] 2.2 为数据模型编写单元测试：验证默认值、序列化、枚举校验

## 3. Provider 抽象层

- [ ] 3.1 创建 `backend/infra/mesh_providers/base.py`：MeshProvider 抽象基类（generate + check_health）
- [ ] 3.2 创建 `backend/infra/mesh_providers/tripo.py`：Tripo3D API 客户端（创建任务 → 轮询 → 下载 GLB），含超时和重试逻辑
- [ ] 3.3 创建 `backend/infra/mesh_providers/hunyuan.py`：Hunyuan3D API 客户端（腾讯云调用 → 下载结果）
- [ ] 3.4 实现 auto 策略：Tripo3D 优先 → 失败/超时 → fallback Hunyuan3D
- [ ] 3.5 为 Provider 编写单元测试：mock API 响应，验证轮询逻辑、fallback 逻辑、错误处理

## 4. 网格后处理管线

- [ ] 4.1 创建 `backend/core/mesh_post_processor.py`：MeshPostProcessor 类骨架，定义 process() 接口和 on_progress 回调
- [ ] 4.2 实现 Step 1 — PyMeshLab 修复：非流形边/顶点修复、法线统一、小洞填充
- [ ] 4.3 实现 Step 2 — trimesh 缩放：计算包围盒、等比缩放到目标尺寸、平移质心到原点
- [ ] 4.4 实现 Step 3 — manifold3d 布尔切削：flat_bottom 平面切削、hole 圆柱差集、slot 长方体差集
- [ ] 4.5 实现 Step 4 — 质量校验：watertight 检查、体积计算、包围盒验证、非流形二次检测
- [ ] 4.6 实现布尔失败优雅降级：捕获 manifold3d 异常，返回仅修复+缩放版本并记录警告
- [ ] 4.7 为后处理管线编写单元测试：用简单几何体（球、立方体）验证修复/缩放/布尔/校验

## 5. OrganicSpec 构建器

- [ ] 5.1 创建 `backend/core/organic_spec_builder.py`：OrganicSpecBuilder 类，LLM 调用将中文 prompt 翻译为英文 + 提取 shape_category + 建议 bounding_box
- [ ] 5.2 为 OrganicSpecBuilder 编写单元测试：mock LLM 响应，验证 OrganicSpec 字段构建

## 6. 后端 API 端点

- [ ] 6.1 创建 `backend/api/organic.py`：`POST /generate/organic` 文本模式 SSE 端点（OrganicSpecBuilder → MeshGenerator → PostProcessor → 导出 → SSE 事件流）
- [ ] 6.2 添加 `POST /generate/organic/upload` 图片模式端点（multipart 接收 → Image-to-3D → PostProcessor → SSE）
- [ ] 6.3 添加 `GET /generate/organic/providers` 端点（返回可用 provider 健康状态）
- [ ] 6.4 在 `backend/main.py` 中挂载 organic_router
- [ ] 6.5 为 API 端点编写集成测试：mock Provider，验证 SSE 事件序列和错误处理

## 7. 导航重构

- [ ] 7.1 修改 `MainLayout.tsx`：侧边栏重构为二级菜单（精密建模子组 + 创意雕塑独立入口 + 设置），处理 selectedKeys 子路径匹配和 defaultOpenKeys
- [ ] 7.2 修改 `Home/index.tsx`：双入口大卡片（精密建模/创意雕塑）+ 三张辅助小卡片（模板/标准/评测）
- [ ] 7.3 更新 Header tagline 为"AI 驱动的 3D 模型生成平台"
- [ ] 7.4 验证所有现有路由导航功能正常，子路由高亮正确

## 8. 前端有机生成页面

- [ ] 8.1 创建 `frontend/src/types/organic.ts`：OrganicWorkflowState、MeshStats、EngineeringCut 等 TypeScript 类型
- [ ] 8.2 创建 `OrganicWorkflow.tsx`：useOrganicWorkflow hook（fetch + ReadableStream SSE 消费）+ 4 步进度条组件
- [ ] 8.3 创建 `OrganicWorkflowContext.tsx`：状态持久化 Context + Provider
- [ ] 8.4 创建 `OrganicInput.tsx`：Tab 切换文本/图片输入组件
- [ ] 8.5 创建 `ConstraintForm.tsx`：包围盒输入 + 工程接口列表（动态增删 EngineeringCut）
- [ ] 8.6 创建 `QualitySelector.tsx`：质量档位 Radio + Provider 选择
- [ ] 8.7 创建 `MeshStatsCard.tsx`：网格统计展示卡片
- [ ] 8.8 创建 `OrganicDownloadButtons.tsx`：STL/3MF 下载按钮
- [ ] 8.9 创建 `OrganicGenerate/index.tsx`：页面主组件，组装所有子组件 + 左右双栏布局
- [ ] 8.10 修改 `App.tsx`：新增 `/generate/organic` 路由 + OrganicWorkflowProvider 包裹
- [ ] 8.11 验证 TypeScript 编译零错误，页面渲染正常

## 9. E2E 验证

- [ ] 9.1 启动后端和前端，配置真实 API Key
- [ ] 9.2 Text-to-3D 端到端测试：输入 prompt + 约束 → 完整走通生成 → 后处理 → 3D 预览 → 下载 STL
- [ ] 9.3 Image-to-3D 端到端测试：上传参考图片 → 完整走通生成 → 3D 预览
- [ ] 9.4 验证导航：侧边栏二级菜单、首页双入口卡片、所有路由正常
- [ ] 9.5 验证状态持久化：生成完成后切换页面再切回，状态保持
