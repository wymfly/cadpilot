## 1. P0.1 PrintabilityChecker 管道接入

- [ ] 1.1 创建 `backend/core/geometry_extractor.py`：从 STEP 文件提取 geometry_info（bounding_box, min_wall_thickness, max_overhang_angle, volume_cm3, min_hole_diameter），使用 CadQuery/OCP 几何查询
- [ ] 1.2 扩展 geometry_extractor 支持 mesh 文件（GLB/STL）：使用 trimesh 分析提取同样的 geometry_info 字段（min_wall_thickness 允许为 None——mesh 壁厚计算昂贵，可跳过）
- [ ] 1.3 为 geometry_extractor 编写单元测试（STEP 路径 + mesh 路径）
- [ ] 1.4 在 `backend/api/generate.py` 的精密建模完成阶段（STEP 生成后），调用 geometry_extractor + PrintabilityChecker.check() + estimate_material() + estimate_print_time()，将完整 PrintabilityResult（含材料估算和时间估算）附加到 SSE `completed` 事件的 `printability` 字段
- [ ] 1.5 在 `backend/api/organic.py` 的有机路径完成阶段，调用 geometry_extractor（mesh 模式）+ PrintabilityChecker.check() + estimate_material() + estimate_print_time()，同样附加完整 PrintabilityResult 到 SSE `completed` 事件
- [ ] 1.6 添加 PrintabilityChecker 管道错误容忍：checker 异常时返回 printability=null + 警告消息，不阻塞生成结果
- [ ] 1.7 前端 `PrintReport` 组件对接真实数据：从 SSE completed 事件的 printability 字段读取并渲染通过/未通过状态、问题列表、材料用量（重量/长度/成本）、打印时间估算
- [ ] 1.8 编写 API 集成测试：精密建模完成后 SSE 事件包含 printability 字段（含 material_estimate 和 time_estimate）

## 2. P0.2 图纸路径 HITL 确认流

- [ ] 2.1 修改 `backend/models/job.py`：添加 `drawing_spec`（JSON）、`drawing_spec_confirmed`（JSON）字段；JobStatus 枚举添加 `AWAITING_DRAWING_CONFIRMATION = "awaiting_drawing_confirmation"` 状态
- [ ] 2.2 拆分图纸管道（D8）：在 `backend/pipeline/pipeline.py` 中新增 `analyze_drawing()` 函数（仅执行 Stage 1：VL 读图 → DrawingSpec）和 `generate_from_drawing_spec()` 函数（执行 Stage 1.5-4：策略→代码生成→执行→精炼，需接收 `image_data` + `drawing_spec` + `output_filepath` 等完整上下文）。修改 `backend/api/generate.py` 的 `/generate/drawing` 路由：调用 `analyze_drawing()` → **保存 `drawing_spec` 到 Job 记录** → 发送 SSE `drawing_spec_ready` 事件（包含 DrawingSpec JSON）→ 将 Job 状态设为 `awaiting_drawing_confirmation` → 结束第一段 SSE 流
- [ ] 2.3 新增 `POST /generate/drawing/{job_id}/confirm` 端点：接收 confirmed_spec + disclaimer_accepted，校验免责声明已接受，**保存 `drawing_spec_confirmed` 到 Job 记录**，从 Job 记录恢复 `image_data`（原始图纸路径），调用 `generate_from_drawing_spec(image_data, confirmed_spec, ...)` 恢复 Stage 1.5-4（注意：Stage 4 SmartRefiner 需要 `original_image` 做 VL 对比），开启第二段 SSE 流
- [ ] 2.4 实现用户修正数据差异计算和**强制 JSON 文件持久化**：对比 original DrawingSpec 和 confirmed DrawingSpec，生成 field-level correction 记录，**必须**写入 `backend/data/corrections/{job_id}.json`（不接受仅内存暂存，P2 迁移到数据库）
- [ ] 2.5 新建 `frontend/src/pages/Generate/DrawingSpecReview.tsx`：分层渲染 DrawingSpec——顶层：零件类型选择器 + AI 置信度标签；中层：overall_dimensions 可编辑数值表 + base_body 参数编辑器；底层：features 列表（可折叠，每项显示类型/参数/可删除）；底部：免责声明 checkbox + "确认并生成"按钮
- [ ] 2.6 前端 SSE 处理：识别 `drawing_spec_ready` 事件，切换到 DrawingSpecReview 界面；confirm 后连接第二段 SSE 流恢复生成流程
- [ ] 2.7 在 `backend/pipeline/sse_bridge.py` 中添加 `drawing_spec_ready` 事件类型支持
- [ ] 2.8 编写图纸路径 HITL 集成测试：验证 analyze_drawing() → 暂停 → confirm → generate_from_drawing_spec() 的完整流程

## 3. P0.3 有机路径 3MF 导出

- [ ] 3.1 在 `backend/api/organic.py` 的导出阶段添加 `mesh.export("model.3mf")`，生成 3MF 文件并设置 threemf_url；写入 3MF 元数据（Title、Designer="cad3dify"、CreationDate）
- [ ] 3.2 验证前端 3MF 下载按钮正常工作

## 4. P1.1 PaddleOCR 引擎接入

- [ ] 4.1 添加 paddleocr（PP-OCRv5）到 pyproject.toml 可选依赖组（`[ocr]`）
- [ ] 4.2 新建 `backend/core/ocr_engine.py`：PaddleOCR 包装函数，适配 `ocr_fn: Callable` 接口；不可用时返回空列表
- [ ] 4.3 为 ocr_engine 编写单元测试（mock PaddleOCR 验证接口适配）
- [ ] 4.4 修改 `backend/core/drawing_analyzer.py`：Stage 1 VLM 分析后，调用 OCRAssistant + merge_ocr_with_vl 融合结果
- [ ] 4.5 为 OCR-VLM 融合编写集成测试：数值字段 OCR 优先、语义字段 VLM 优先、不一致时 OCR 胜出

## 5. P1.2 IntentParser 替换 keyword 匹配

- [ ] 5.1 修改 `backend/api/generate.py`：将 `_match_template()` 的调用替换为 IntentParser.parse()，注入 `llm_callable`（使用 ChatModelFactory 创建）；保留 _match_template 为 fallback
- [ ] 5.2 实现路由逻辑：confidence > 0.7 且有匹配模板 → 轨道 A；否则 → 轨道 B（LLM 代码生成）
- [ ] 5.3 添加 IntentParser 不可用时的降级处理：LLM 调用失败自动切换到 keyword 匹配
- [ ] 5.4 编写 IntentParser 路由测试：高置信度匹配、低置信度 fallback、LLM 失败降级

## 6. P2.1 SQLite 持久化

- [ ] 6.1 添加 `aiosqlite>=0.20.0`、`sqlalchemy[asyncio]`、alembic 依赖到 pyproject.toml（钉死 aiosqlite 最低版本以规避 SQLAlchemy #13039 连接挂起问题）
- [ ] 6.2 新建 `backend/db/database.py`：async SQLAlchemy engine + session factory，使用 SQLite + aiosqlite；配置 `connect_args={"timeout": 30}`（busy timeout）和 `pool_pre_ping=True`
- [ ] 6.3 新建 `backend/db/models.py`：定义 JobModel、OrganicJobModel 和 UserCorrectionModel（SQLAlchemy ORM 模型），包含所有 JSON 字段。OrganicJobModel 覆盖 `backend/models/organic_job.py` 的数据
- [ ] 6.4 新建 `backend/db/repository.py`：async CRUD 操作（create_job, get_job, update_job, list_jobs, create_correction, list_corrections），以及 organic job 的对应操作（create_organic_job, get_organic_job, update_organic_job, list_organic_jobs）
- [ ] 6.5 配置 Alembic：初始化 alembic.ini + env.py，创建初始迁移脚本
- [ ] 6.6 重构 `backend/models/job.py` 和 `backend/models/organic_job.py`：将两者的内存 dict 操作替换为 repository 调用，保持 API 签名不变
- [ ] 6.7 迁移 P0 阶段的 JSON 文件暂存数据到数据库（user_corrections 导入脚本，读取 `backend/data/corrections/*.json`）
- [ ] 6.8 为 repository 层编写单元测试（CRUD + 分页 + JSON 字段查询，覆盖 Job 和 OrganicJob 两种模型）
- [ ] 6.9 编写集成测试：进程重启后 Job 和 OrganicJob 仍可查询

## 7. P2.2 我的零件库 / 历史

- [ ] 7.1 新增 `GET /jobs` API：支持分页（page, page_size）、状态过滤（status）、类型过滤（input_type: text/drawing/organic）、按创建时间降序排列
- [ ] 7.2 新增 `POST /jobs/{job_id}/regenerate` API：复制历史 Job 参数，创建新 Job 并跳转到参数确认流程
- [ ] 7.3 新增 `DELETE /jobs/{job_id}` API：删除 Job 记录 + 关联输出文件，保留 user_corrections
- [ ] 7.4 新建 `frontend/src/pages/History/HistoryPage.tsx`：卡片列表（缩略图 + 零件名 + 时间 + 状态），分页控件
- [ ] 7.5 新建 `frontend/src/pages/History/JobDetailPage.tsx`：3D 预览 + 参数详情 + PrintReport + 下载按钮 + "改参数重生成"按钮
- [ ] 7.6 添加前端路由 `/history` 和 `/history/:jobId`
- [ ] 7.7 在首页或导航栏添加"我的零件库"入口
- [ ] 7.8 编写历史页面 API 测试（分页、过滤、删除、重生成）

## 8. P2.3 参数实时预览 API

- [ ] 8.1 新建 `backend/api/preview.py`：`POST /preview/parametric` 接收 template_name + params，调用 TemplateEngine 渲染 + CadQuery 执行 + STEP→GLB 转换，返回 GLB URL
- [ ] 8.2 实现 draft 质量模式：在 TemplateEngine 或 CadQuery 执行中降低 tessellation 分辨率（减面 70%）
- [ ] 8.3 实现预览缓存：(template_name, params_hash) → GLB URL，模板更新时清除对应缓存
- [ ] 8.4 添加 5s 硬超时：CadQuery 执行超时返回 HTTP 408（分级目标：简单零件 <1s，中等 <3s，复杂 <5s）
- [ ] 8.5 修改前端 ParamForm：参数变更后 debounce 300ms 触发预览请求，Three.js viewer 热替换 GLB（注意旧 GLB 内存释放：dispose geometry + material + texture）
- [ ] 8.6 编写预览 API 单元测试（成功预览、参数校验失败、超时、缓存命中）
