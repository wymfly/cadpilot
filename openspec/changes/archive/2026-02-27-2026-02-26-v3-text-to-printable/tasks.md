# cad3dify V3 Tasks

> **设计文档:** [design.md](./design.md)
> **提案文档:** [proposal.md](./proposal.md)

---

## Phase 1：架构重构 + 快速收益

> **目标:** 前后端分离 + STL 导出 + 3D 预览 + 评测基准
> **预计工作量:** 2-3 周

### Task 1.1: 项目目录结构重构
- **状态:** ✅ 已完成
- **标签:** [backend] [architecture]
- **范围:** 整体目录结构
- **AC:**
  - AC1: `backend/` 目录包含 `api/`, `core/`, `knowledge/`, `pipeline/`, `models/`, `infra/`
  - AC2: `frontend/` 目录包含 React + TypeScript + Vite 骨架
  - AC3: 现有 `cad3dify/` 模块迁移到 `backend/` 对应子目录
  - AC4: `import cad3dify` 兼容性保持（重导出）
  - AC5: 现有测试可通过
- **产出:**
  - 重构后的目录结构
  - pyproject.toml 更新
- **验证:**
  - `pytest` 全部通过
  - `python -c "from cad3dify.pipeline import Pipeline"` 成功

### Task 1.2: FastAPI 后端骨架 + PipelineConfig
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/api/`, `backend/main.py`, `backend/config.py`, `backend/models/pipeline_config.py`
- **依赖:** Task 1.1
- **AC:**
  - AC1: FastAPI 应用可在 `:8780` 启动
  - AC2: `/api/health` 健康检查端点
  - AC3: `/api/generate` SSE 流式端点（接收图纸 + `pipeline_config` → 调用 V2 管道 → 流式返回进度）
  - AC4: CORS 配置支持前端开发
  - AC5: `PipelineConfig` 数据模型（所有增强步骤独立开关，见 ADR-6）
  - AC6: 三个预设模式（fast / balanced / precise）+ custom 自定义
  - AC7: `GET /api/pipeline/tooltips` — 返回所有管道选项的 TooltipSpec（title/description/when_to_use/cost/default）
  - AC8: `GET /api/pipeline/presets` — 返回预设配置列表
- **产出:**
  - `backend/main.py` — FastAPI 入口
  - `backend/api/generate.py` — 生成端点（接收 pipeline_config）
  - `backend/api/pipeline.py` — 管道配置 API（tooltips + presets）
  - `backend/models/pipeline_config.py` — PipelineConfig + TooltipSpec 模型
  - `backend/config.py` — 应用配置（Pydantic Settings）
- **验证:**
  - `uvicorn backend.main:app` 启动成功
  - `curl localhost:8780/api/health` 返回 200
  - SSE 端点可流式返回事件
  - `/api/pipeline/tooltips` 返回完整 Tooltip 数据
  - 传入 `preset: "fast"` 时跳过非必要步骤

### Task 1.3: React 前端骨架 + 管道配置组件
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/`
- **AC:**
  - AC1: Vite + React 18 + TypeScript 5.6 项目初始化
  - AC2: 路由配置（/, /generate, /templates, /settings）
  - AC3: 布局组件（Header, Sidebar, Content）
  - AC4: API 客户端（axios/fetch + SSE EventSource）
  - AC5: 开发服务器 `:3001` 可访问
  - AC6: `PipelineConfigBar` 组件 — 预设模式切换（⚡快速 / ⚖️均衡 / 🎯精确 / ⚙️自定义）
  - AC7: 自定义模式展开面板 — 每个增强步骤 Checkbox + `?` Tooltip 图标
  - AC8: Tooltip 数据从 `/api/pipeline/tooltips` 加载，hover `?` 图标显示：说明 / 适用场景 / 代价
  - AC9: 渐进披露 — 默认折叠自定义面板，仅显示预设按钮
- **产出:**
  - `frontend/` 完整骨架
  - `frontend/src/components/PipelineConfigBar/` — 管道配置组件
  - `package.json` 含必要依赖（含 Ant Design）
- **验证:**
  - `cd frontend && npm run dev` 启动成功
  - 页面路由切换正常
  - 预设模式切换正常，自定义面板展开/折叠
  - Tooltip hover 显示完整说明

### Task 1.4: STL/3MF 格式导出
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/format_exporter.py`, `backend/api/export.py`
- **AC:**
  - AC1: STEP → STL 导出（可配置 linear/angular deflection）
  - AC2: STEP → 3MF 导出
  - AC3: STEP → glTF 导出（供前端 Three.js 预览）
  - AC4: `/api/export` API 端点
  - AC5: 导出文件可被 Cura/PrusaSlicer 正确加载
- **产出:**
  - `backend/core/format_exporter.py` — FormatExporter 类
  - `backend/api/export.py` — 导出 API
- **验证:**
  - 单元测试：已知 STEP → STL 体积/面数一致
  - STL 文件在 3D 打印切片软件中可打开

### Task 1.5: 体积估算验证器
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/validators.py`
- **AC:**
  - AC1: `estimate_volume(spec)` 从 DrawingSpec 估算理论体积
  - AC2: 与 `GeometryResult.volume` 对比，偏差 > 30% 标记
  - AC3: 集成到 SmartRefiner 的诊断上下文
- **产出:**
  - `estimate_volume()` 函数
- **验证:**
  - 单元测试：已知参数的旋转体体积估算误差 < 5%

### Task 1.6: Token 用量监控
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/infra/token_tracker.py`, `backend/pipeline/pipeline.py`
- **AC:**
  - AC1: LangChain BaseCallbackHandler 记录每次 LLM 调用的 in/out token
  - AC2: 管道运行结束输出 `pipeline_stats.json`
  - AC3: 包含各 stage 耗时、token 消耗、总计
- **产出:**
  - `backend/infra/token_tracker.py`
- **验证:**
  - 运行一次管道后 `pipeline_stats.json` 内容完整

### Task 1.7: 评测基准框架 + 失败分类
- **状态:** ✅ 已完成
- **标签:** [backend] [test]
- **范围:** `backend/benchmark/`
- **依赖:** Task 1.5, Task 1.6
- **AC:**
  - AC1: `BenchmarkRunner` 可遍历数据集目录运行管道
  - AC2: 计算 5 项指标（编译通过率、类型准确率、参数准确率、几何匹配率、平均耗时）
  - AC3: 输出 Markdown + JSON 报告
  - AC4: `python -m cad3dify.benchmark run` CLI 入口
  - AC5: 初始数据集 5 个 case（手工标注）
  - AC6: **失败分类统计**（合并自方案 X.2）— 对每个失败 case 自动分类：类型识别错误 / 标注漏读 / 代码执行失败 / 结构性错误 / 尺寸偏差，按频率排序输出到报告
  - AC7: `POST /api/benchmark/run` API 端点（SSE 流式返回进度 + 结果）
  - AC8: `GET /api/benchmark/history` — 历史评测报告列表
  - AC9: `GET /api/benchmark/history/{run_id}` — 某次评测的详细报告
- **产出:**
  - `backend/benchmark/runner.py`
  - `backend/benchmark/metrics.py`
  - `backend/benchmark/reporter.py`
  - `backend/api/benchmark.py` — 评测 API
  - `benchmarks/v1/` 初始数据集
- **验证:**
  - `python -m cad3dify.benchmark run --dataset benchmarks/v1/` 输出报告
  - 报告含失败分类统计（按频率排序）
  - `POST /api/benchmark/run` 可通过 API 触发评测

### Task 1.10: 评测基准前端页面
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/src/pages/Benchmark/`
- **依赖:** Task 1.7, Task 1.3
- **AC:**
  - AC1: 评测运行页面（选择数据集 → 触发运行 → SSE 进度显示）
  - AC2: 历史报告列表（日期/指标摘要/详情链接）
  - AC3: 报告详情页（指标图表 + 失败分类统计 + 逐 case 结果表）
- **产出:**
  - `frontend/src/pages/Benchmark/` 页面组件
- **验证:**
  - 完整评测运行流程可走通（触发→进度→报告查看）

### Task 1.8: 代码执行安全沙箱
- **状态:** ✅ 已完成
- **标签:** [backend] [security]
- **范围:** `backend/infra/sandbox.py`, `backend/infra/agents.py`
- **AC:**
  - AC1: LLM 生成的 CadQuery 代码在独立子进程中执行（`subprocess` + 超时）
  - AC2: 文件系统隔离 — 执行进程只能写入指定临时目录，不可访问项目或系统文件
  - AC3: 资源限制 — 单次执行超时 60s、内存上限 2GB
  - AC4: 禁用危险模块 — `os.system`、`subprocess`、`eval`、`exec`、`__import__` 等（AST 预检 + 运行时 hook）
  - AC5: API 层基础鉴权 — API Key 验证（后续 Phase 可升级为用户系统）
  - AC6: 并发限制 — 单实例最多 N 个并行执行任务（防 DoS）
- **产出:**
  - `backend/infra/sandbox.py` — 安全执行器
  - `backend/config.py` 增加安全相关配置项
- **验证:**
  - 恶意代码测试：`import os; os.remove('/')` 被拦截
  - 超时测试：死循环代码 60s 后被终止
  - 文件隔离测试：执行代码无法读取项目目录

### Task 1.9: 3D 预览组件
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/src/components/Viewer3D/`
- **依赖:** Task 1.3, Task 1.4
- **AC:**
  - AC1: Three.js / React Three Fiber 加载 glTF 文件
  - AC2: 旋转/缩放/平移交互
  - AC3: 线框/实体模式切换
  - AC4: 标准视角快捷切换（正视/俯视/侧视/等轴测）
  - AC5: 响应式布局
- **产出:**
  - `Viewer3D` React 组件
- **验证:**
  - 加载测试 glTF 文件渲染正常
  - 交互流畅（60fps）

---

## Phase 2：生成质量引擎

> **目标:** 管道级质量提升，精度 3-5% → 1-2%
> **预计工作量:** 2-3 周
> **依赖:** Phase 1

### Task 2.1: Best-of-N 多路生成 + 代码预检
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/code_generator.py`, `backend/pipeline/pipeline.py`
- **依赖:** Task 1.2（PipelineConfig 模型）
- **AC:**
  - AC1: 生成 N 份代码（N 由 `PipelineConfig.best_of_n` 控制，默认 3，`fast` 模式 =1 关闭）
  - AC2: 全部执行，收集几何验证结果
  - AC3: `score_candidate()` 综合打分（编译 50 + 体积 20 + 包围盒 20 + 拓扑 10）
  - AC4: 取最高分候选进入 SmartRefiner
  - AC5: SSE 流式返回各候选进度
  - AC6: **CadQuery API 白名单约束**（合并自方案 2.2）— prompt 中注入禁用 API 列表 + 推荐用法，由 `PipelineConfig.api_whitelist` 控制
  - AC7: **执行前 AST 静态检查**（合并自方案 2.3）— 检查 export 语句、未定义变量、禁用 API 调用，由 `PipelineConfig.ast_pre_check` 控制，不通过的候选直接 0 分跳过执行
- **产出:**
  - `backend/core/code_generator.py` 中的 `generate_best_of_n()`
  - `score_candidate()` 打分函数
  - `ast_pre_check()` 静态检查函数
  - CadQuery API 白名单数据
- **验证:**
  - benchmark 对比：N=3 vs N=1 的编译通过率和几何匹配率
  - 至少 5 个 case 中 N=3 优于 N=1
  - AST 检查拦截已知的坏代码模式（缺 export、未定义变量）

### Task 2.2: 多视角渲染
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/infra/render.py`, `backend/core/smart_refiner.py`
- **AC:**
  - AC1: 从 4 个标准视角渲染（正面、俯视、侧面、等轴测）
  - AC2: VL 同时接收所有视图 + 原始图纸
  - AC3: `_COMPARE_PROMPT` 更新为逐视图对比
  - AC4: SSE 返回各视角渲染图
- **产出:**
  - 多视角渲染配置
  - 更新后的 VL prompt
- **验证:**
  - benchmark 对比：多视角 vs 单视角的几何匹配率

### Task 2.3: 回滚机制
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/pipeline/pipeline.py`
- **AC:**
  - AC1: refinement 循环中保存上一轮代码和几何评分
  - AC2: 新一轮几何评分退化 > 10% 时回滚到上一版本
  - AC3: 回滚事件通过 SSE 通知前端
  - AC4: 回滚次数记录到 pipeline_stats
- **产出:**
  - 回滚逻辑（~20 行代码）
- **验证:**
  - 构造退化 case（人工或 mock），验证回滚触发

### Task 2.4: 拓扑验证
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/validators.py`
- **AC:**
  - AC1: `count_topology()` 统计 STEP 的圆柱面数、平面数、shell 数、solid 数
  - AC2: 与 spec.features 期望值对比（孔数 ↔ 圆柱面对数）
  - AC3: 拓扑偏差注入 SmartRefiner 诊断上下文
- **产出:**
  - `count_topology()` 函数
- **验证:**
  - 单元测试：已知零件的拓扑统计结果正确

### Task 2.5: 结构化 VL 反馈
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/smart_refiner.py`
- **AC:**
  - AC1: VL prompt 要求输出 JSON issues 列表
  - AC2: 每个 issue 包含 type/severity/description/expected/location
  - AC3: Coder 修复 prompt 直接引用结构化 issues
- **产出:**
  - 更新后的 `_COMPARE_PROMPT`
  - issues 解析逻辑
- **验证:**
  - VL 输出格式符合 JSON schema

### Task 2.6: 截面分析验证
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/validators.py`
- **AC:**
  - AC1: 在指定高度切横截面，测量外径
  - AC2: 与 spec.base_body.profile 中对应层的 diameter 比对
  - AC3: 偏差 > 10% 的层标记为不匹配
- **产出:**
  - `cross_section_analysis()` 函数
- **验证:**
  - 单元测试：阶梯轴截面分析结果与预期一致

### Task 2.7: benchmark 对比报告
- **状态:** ✅ 已完成
- **标签:** [backend] [test]
- **范围:** `backend/benchmark/`
- **依赖:** Task 2.1, 2.2, 2.3, 2.4
- **AC:**
  - AC1: 运行 benchmark baseline（Phase 1 状态）
  - AC2: 运行 benchmark enhanced（Phase 2 状态）
  - AC3: 生成对比报告（每项指标的提升幅度）
- **产出:**
  - `results/benchmark_phase2_comparison.md`
- **验证:**
  - 对比报告中至少 3 项指标有显著提升

---

## Phase 3：参数化模板 + 知识库管理

> **目标:** 模板覆盖的零件精度 < 1%，知识库可视化管理
> **预计工作量:** 3-4 周
> **依赖:** Phase 2

### Task 3.1: features 结构化模型
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/models/drawing_spec.py`, `backend/knowledge/`
- **AC:**
  - AC1: `features: list[dict]` → `features: list[Feature]`（Pydantic union type）
  - AC2: 使用 `part_types.py` 中已有的 `HolePatternSpec`, `FilletSpec`, `ChamferSpec`
  - AC3: 知识库示例的 features 同步迁移
  - AC4: 所有引用 `features` 的代码适配新结构
- **产出:**
  - 结构化 Feature 模型
  - 迁移后的知识库
- **验证:**
  - 所有现有测试通过
  - 知识库示例的 features 可正确序列化/反序列化

### Task 3.2: ParametricTemplate 数据模型
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/models/template.py`
- **AC:**
  - AC1: `ParametricTemplate` Pydantic 模型定义
  - AC2: `ParamDefinition` 含 name/display_name/unit/type/range/default/depends_on
  - AC3: 模板存储为 YAML 文件（便于人工编辑）
  - AC4: 模板加载器：从 YAML → ParametricTemplate
- **产出:**
  - `backend/models/template.py`
  - YAML schema 定义
- **验证:**
  - YAML ↔ Pydantic 模型序列化/反序列化正确

### Task 3.3: ParametricTemplateEngine 核心
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/template_engine.py`
- **依赖:** Task 3.2
- **AC:**
  - AC1: `find_match(part_type, params)` — 精确/模糊匹配
  - AC2: `generate_code(template, params)` — Jinja2 渲染 CadQuery 代码
  - AC3: `validate_params(template, params)` — 约束规则检查
  - AC4: 生成的代码可被 CadQuery 执行出有效 STEP
- **产出:**
  - `backend/core/template_engine.py`
- **验证:**
  - 单元测试：法兰模板 + 参数 → 有效 CadQuery 代码 → 有效 STEP

### Task 3.4: 首批参数化模板（7 类型 × 2-3 变体）
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/knowledge/templates/`
- **依赖:** Task 3.3
- **AC:**
  - AC1: ROTATIONAL — 法兰盘、圆盘（2 个模板）
  - AC2: ROTATIONAL_STEPPED — 阶梯轴、法兰轴（2 个模板）
  - AC3: PLATE — 矩形板、带孔板（2 个模板）
  - AC4: BRACKET — L 型支架、U 型支架（2 个模板）
  - AC5: SHELL — 圆柱壳、箱体壳（2 个模板）
  - AC6: HOUSING — 轴承座、电机壳（2 个模板）
  - AC7: GEAR — 直齿圆柱齿轮（1 个模板）
  - AC8: 每个模板包含参数定义、约束规则、CadQuery 代码模板
  - AC9: 每个模板经过 CadQuery 执行验证
- **产出:**
  - 13-15 个 YAML 模板文件
  - 每个模板的测试参数组
- **验证:**
  - 全部模板可生成有效 STEP
  - 尺寸精度 < 1%

### Task 3.5: 模板管理 API
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/api/templates.py`
- **依赖:** Task 3.3
- **AC:**
  - AC1: GET /api/templates — 模板列表（支持 part_type 过滤）
  - AC2: GET /api/templates/{name} — 模板详情
  - AC3: POST /api/templates — 创建模板
  - AC4: PUT /api/templates/{name} — 更新模板
  - AC5: DELETE /api/templates/{name} — 删除模板
  - AC6: POST /api/templates/{name}/validate — 验证模板参数
  - AC7: POST /api/templates/{name}/preview — 生成预览（glTF + 尺寸信息）
- **产出:**
  - `backend/api/templates.py`
- **验证:**
  - API 集成测试覆盖 CRUD + validate + preview

### Task 3.6: 知识库管理前端
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/src/pages/Templates/`
- **依赖:** Task 3.5, Task 1.9
- **AC:**
  - AC1: 模板列表页（按类型分组、搜索、过滤）
  - AC2: 模板详情页（参数定义表、代码预览、3D 预览）
  - AC3: 模板编辑器（YAML 编辑 + 实时验证 + 预览刷新）
  - AC4: 创建/删除模板
  - AC5: 在线验证（输入参数 → 生成预览 → 显示验证结果）
- **产出:**
  - Templates 页面组件
- **验证:**
  - 完整 CRUD 操作流程可走通

### Task 3.7: 向量检索替代 Jaccard
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/modeling_strategist.py`, `backend/infra/rag.py`
- **AC:**
  - AC1: 使用 embedding 模型编码 DrawingSpec 描述
  - AC2: pgvector 存储向量 + 元数据
  - AC3: `find_similar()` 语义检索 top-K 最相似模板/示例
  - AC4: 保留 Jaccard 作为 fallback（向量检索无结果时）
- **产出:**
  - `backend/infra/rag.py`
  - pgvector 迁移脚本
- **验证:**
  - 检索结果质量优于纯 Jaccard（人工评估 10 case）

### Task 3.8: 知识库扩充（短期 fallback）
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/knowledge/examples/`
- **说明:** TaggedExample 是模板未覆盖零件的 LLM 自由生成 fallback 素材。Phase 5 的 170K RAG 数据集会逐步取代此角色，届时 TaggedExample 仅保留为最高质量的"金标准"示例子集。
- **AC:**
  - AC1: ROTATIONAL 补充到 8 个示例
  - AC2: ROTATIONAL_STEPPED 补充到 8 个示例
  - AC3: PLATE 补充到 6 个示例
  - AC4: BRACKET 补充到 6 个示例
  - AC5: SHELL 补充到 5 个示例
  - AC6: HOUSING 补充到 5 个示例
  - AC7: 每个示例经过 CadQuery 执行验证
- **产出:**
  - 新增 ~25 个 TaggedExample
- **验证:**
  - 全部示例可生成有效 STEP
  - benchmark 代码首次正确率提升

---

## Phase 4：交互式工作流 + 意图理解

> **目标:** 自然语言输入 + 交互确认 → 精度 < 0.5%
> **预计工作量:** 4-5 周
> **依赖:** Phase 3

### Task 4.1: IntentSpec 数据模型
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/models/intent.py`
- **AC:**
  - AC1: `IntentSpec` 含 part_category/part_type/known_params/missing_params/constraints/reference_image/confidence/raw_text（与 design.md 定义一致）
  - AC2: `PreciseSpec` 继承 DrawingSpec，增加 source/confirmed_by_user/intent/recommendations_applied 字段
  - AC3: IntentSpec → PreciseSpec 转换逻辑（填充用户确认后的完整参数）
- **产出:**
  - `backend/models/intent.py`
- **验证:**
  - 序列化/反序列化测试

### Task 4.2: IntentParser 实现
- **状态:** ✅ 已完成
- **标签:** [backend] [agent]
- **范围:** `backend/core/intent_parser.py`
- **依赖:** Task 4.1, Task 3.2（ParamDefinition 用于缺失参数识别）
- **AC:**
  - AC1: LLM 驱动的意图解析，**强制使用 structured output / function calling**（合并自方案 1.4 结构化输出约束）— 不用自由文本 + 正则解析，而是 JSON schema 约束 LLM 输出固定结构
  - AC2: 零件类型识别（映射到已知 PartType）
  - AC3: 参数提取（数值 + 单位解析）
  - AC4: 缺失参数识别（根据 PartType 的 ParamDefinition）
  - AC5: 约束条件提取（"需要和 M10 配合" → 约束）
  - AC6: 置信度评估
- **产出:**
  - `backend/core/intent_parser.py`
- **验证:**
  - 20 个自然语言输入的意图识别准确率 ≥ 95%（与 proposal 成功标准一致）
  - 输出 100% 符合 IntentSpec JSON schema（无格式解析失败）

### Task 4.3: 工程标准知识库
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/engineering_standards.py`, `backend/knowledge/standards/`
- **AC:**
  - AC1: 螺栓/螺母标准数据（M6-M30 通孔、沉孔）
  - AC2: 法兰标准（GB/T 9119 DN25-DN300 基本参数）
  - AC3: 配合公差数据（H7/h6, H7/p6 等常用配合）
  - AC4: 键/键槽标准（GB/T 1096 基本尺寸）
  - AC5: 齿轮模数系列
  - AC6: `recommend_params()` — 基于已知参数推荐缺失值
  - AC7: `check_constraints()` — 参数间工程一致性检查
- **产出:**
  - `backend/core/engineering_standards.py`
  - `backend/knowledge/standards/*.yaml` 标准数据文件
- **验证:**
  - 法兰盘参数推荐测试：给外径 → 推荐 PCD/孔数/孔径
  - 约束检查测试：PCD < 外径 检测到

### Task 4.4: 工程标准 API + 前端
- **状态:** ✅ 已完成
- **标签:** [backend] [frontend]
- **范围:** `backend/api/standards.py`, `frontend/src/pages/Standards/`
- **依赖:** Task 4.3
- **AC:**
  - AC1: GET /api/standards — 标准分类列表
  - AC2: GET /api/standards/{category} — 某类标准详情（如螺栓标准表）
  - AC3: POST /api/standards/recommend — 参数推荐
  - AC4: POST /api/standards/check — 约束检查
  - AC5: 前端标准浏览页（按类别展示）
  - AC6: 前端标准查询组件（选类别 → 查参数）
- **产出:**
  - API + 前端页面
- **验证:**
  - 端到端：输入"M10 螺栓" → 返回通孔直径推荐

### Task 4.5: 参数确认 UI（表单 + 滑块）
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/src/components/ParamForm/`, `frontend/src/components/ParamSlider/`
- **依赖:** Task 1.9, Task 4.3
- **AC:**
  - AC1: 动态参数表单（根据 ParamDefinition 自动生成）
  - AC2: 每个参数显示推荐值 + 推荐理由 + 来源标准
  - AC3: 参数滑块实时调整（范围由 min/max 确定）
  - AC4: 滑块调整 → 触发后端重新生成 → 3D 预览刷新
  - AC5: 约束违反实时提示（红色警告）
  - AC6: 确认按钮 → 提交 PreciseSpec
- **产出:**
  - ParamForm 组件
  - ParamSlider 组件
- **验证:**
  - 法兰盘参数表单：调整外径 → 滑块联动 → 3D 预览更新

### Task 4.6: 生成工作台集成
- **状态:** ✅ 已完成
- **标签:** [frontend] [backend]
- **范围:** `frontend/src/pages/Generate/`, `backend/api/generate.py`
- **依赖:** Task 4.2, Task 4.5, Task 1.9
- **AC:**
  - AC1: 对话式输入 → IntentParser → 参数确认 → 生成 → 预览的完整流程
  - AC2: SSE 事件驱动的分阶段 UI（意图解析 → 参数确认 → 生成进度 → 预览 → 导出）
  - AC3: 左右分栏布局（对话+参数 | 3D预览）
  - AC4: 输出下载区（STEP/STL/3MF/代码）
  - AC5: 任务会话协议 — `POST /api/generate` 返回 `job_id`，`params_confirmation` 阶段暂停，`POST /api/generate/{job_id}/confirm` 恢复流程（见 design.md 生成任务会话协议）
  - AC6: 前端状态机匹配后端完整状态（CREATED → INTENT_PARSED → AWAITING_CONFIRMATION → GENERATING → REFINING → COMPLETED，含 VALIDATION_FAILED 异常分支）
- **产出:**
  - Generate 页面完整实现
- **验证:**
  - 端到端：输入"法兰盘 外径100" → 参数确认 → 3D 预览 → 下载 STL

### Task 4.7: 可打印性检查
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/printability.py`
- **AC:**
  - AC1: 壁厚检查（面对距离分析）
  - AC2: 悬挑角度检查（面法线与 Z 轴夹角）
  - AC3: 最小孔径检查（圆柱面半径提取）
  - AC4: 最小筋厚检查（面间距分析）
  - AC5: 构建体积检查（包围盒 vs 打印机构建体积）
  - AC6: FDM/SLA/SLS 三种预设配置
- **产出:**
  - `backend/core/printability.py`
  - `backend/models/printability.py`
- **验证:**
  - 已知壁厚不足的模型 → 检测到 wall_thickness issue
  - 大悬挑模型 → 检测到 overhang issue

### Task 4.8: 可打印性报告 UI
- **状态:** ✅ 已完成
- **标签:** [frontend]
- **范围:** `frontend/src/components/PrintReport/`
- **依赖:** Task 4.7
- **AC:**
  - AC1: 检查项列表（✅/⚠️/❌ 状态）
  - AC2: 每个 issue 的描述 + 修复建议
  - AC3: 打印配置选择（FDM/SLA/SLS 预设；自定义配置在 Task 4.9 完成后可用）
  - AC4: 材料用量 + 预估打印时间显示
  - AC5: 打印方向推荐可视化
- **产出:**
  - PrintReport 组件
- **验证:**
  - 完整的可打印性报告渲染

### Task 4.9: 打印配置管理
- **状态:** ✅ 已完成
- **标签:** [frontend] [backend]
- **范围:** `frontend/src/pages/Settings/`, `backend/api/settings.py`
- **AC:**
  - AC1: 预设打印配置（FDM/SLA/SLS 标准配置）
  - AC2: 自定义配置 CRUD
  - AC3: 配置持久化（数据库或配置文件）
- **产出:**
  - 设置页面打印配置管理
- **验证:**
  - 创建自定义配置 → 生成时选用 → 检查结果使用自定义阈值

---

## Phase 5：AI 增强 + 多模态

> **目标:** RAG 增强代码质量 + 多模态输入支持
> **预计工作量:** 3-4 周
> **依赖:** Phase 4

### Task 5.1: Text-to-CadQuery 数据集获取与处理
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/infra/rag.py`, 数据处理脚本
- **AC:**
  - AC1: 下载 Text-to-CadQuery 170K 数据集
  - AC2: 数据质量过滤（执行验证，过滤无效代码）
  - AC3: embedding 编码（文本描述 → 向量）
  - AC4: 向量化入库（pgvector）
  - AC5: 检索 API（query text → top-K 相似代码）
- **产出:**
  - 数据处理管道
  - 向量化数据库
- **验证:**
  - 检索质量人工评估（10 query，每个 top-5 相关性评分）

### Task 5.2: RAG 增强代码生成
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/code_generator.py`
- **依赖:** Task 5.1
- **AC:**
  - AC1: 生成前检索 top-3 相似代码作为 few-shot 示例
  - AC2: 注入 Coder prompt（示例代码 + 对应描述）
  - AC3: 可配置是否启用 RAG
  - AC4: benchmark 对比 RAG vs 无 RAG
- **产出:**
  - RAG 增强的代码生成逻辑
- **验证:**
  - benchmark: RAG 模式代码首次正确率提升 ≥ 20%

### Task 5.3: OCR 辅助 + 两阶段分析
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/drawing_analyzer.py`
- **AC:**
  - AC1: PaddleOCR / Tesseract 提取图纸文本和数值
  - AC2: 尺寸标注格式解析（φ、R、×、±）
  - AC3: OCR 结果注入 VL prompt 辅助分析
  - AC4: VL 和 OCR 交叉验证（一致 → 高置信度，不一致 → 优先 OCR 数值/VL 语义）
  - AC5: **两阶段分析**（合并自方案 1.3）— Pass 1（全局）识别整体结构（零件类型、阶梯数、孔数），Pass 2（局部）裁剪标注区域精确读取尺寸值。由 `PipelineConfig.two_pass_analysis` 控制
- **产出:**
  - OCR 集成模块
  - 交叉验证逻辑
  - 两阶段分析管道
- **验证:**
  - benchmark: OCR 辅助 vs 纯 VL 的参数准确率对比
  - 两阶段分析减少"大局对、细节错"的 case 数

### Task 5.4: 多模型投票 + Self-consistency
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/core/drawing_analyzer.py`
- **AC:**
  - AC1: 并行调用 2-3 个 VL 模型，由 `PipelineConfig.multi_model_voting` 控制
  - AC2: 数值字段取中位数，枚举字段取多数票
  - AC3: 不一致字段标为低置信度
  - AC4: 可配置投票模型列表
  - AC5: **Self-consistency**（合并自方案 1.5）— 同模型同 prompt 跑 N 次（由 `PipelineConfig.self_consistency_runs` 控制，默认 1=关闭），取众数，不一致维度标为低置信度。与多模型投票共用聚合逻辑
- **产出:**
  - 多模型投票 + self-consistency 统一聚合逻辑
- **验证:**
  - benchmark: 投票 vs 单模型的类型准确率和参数准确率
  - self-consistency N=3 vs N=1 的参数稳定性对比

### Task 5.5: 参考图片理解
- **状态:** ✅ 已完成
- **标签:** [backend] [agent]
- **范围:** `backend/core/intent_parser.py`
- **依赖:** Task 4.2
- **AC:**
  - AC1: 接受参考图片 + 文字修改描述
  - AC2: VL 分析参考图片 → 提取基础参数
  - AC3: 文字修改应用到参数（"外径改为 150"）
  - AC4: 参数确认流程（含图片对比）
- **产出:**
  - 多模态 IntentParser
- **验证:**
  - 参考图片 + "外径改为 150" → 正确修改参数

### Task 5.6: 成本优化
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/pipeline/pipeline.py`, `backend/infra/chat_models.py`
- **AC:**
  - AC1: 模型降级策略（Round 1 用 max，Round 2+ 用 plus）
  - AC2: 缓存机制（同一图片 Stage 1 结果哈希缓存，TTL 1h）
  - AC3: 可配置的模型降级规则
- **产出:**
  - 模型降级 + 缓存逻辑
- **验证:**
  - 成本对比：降级 vs 不降级的 token 消耗

---

## Phase 6：高级能力

> **目标:** 领域深度能力 + 前沿 AI 技术
> **预计工作量:** 4-6 周
> **依赖:** Phase 5

### Task 6.1: 微调数据管道
- **状态:** ✅ 已完成
- **标签:** [backend] [agent]
- **范围:** 新建 `scripts/training/`
- **AC:**
  - AC1: DeepCAD JSON → CadQuery 代码转换管道（参考 Text-to-CadQuery）
  - AC2: 执行验证 + 视觉评估过滤
  - AC3: SFT 数据格式转换（instruction/input/output）
  - AC4: 数据质量统计报告
- **产出:**
  - 训练数据管道脚本
  - SFT 数据集
- **验证:**
  - 转换后的数据集中有效代码比例 ≥ 85%

### Task 6.2: SFT + GRPO 微调
- **状态:** ✅ 已完成
- **标签:** [backend] [agent]
- **范围:** `scripts/training/`
- **依赖:** Task 6.1
- **AC:**
  - AC1: Qwen2.5-3B/7B SFT 训练脚本
  - AC2: GRPO 强化学习（几何奖励函数：CD < 10⁻⁵ 满分）
  - AC3: 模型评估（Chamfer Distance, 编译通过率）
  - AC4: 模型部署接入 chat_models
- **产出:**
  - 微调训练脚本
  - 微调模型
- **验证:**
  - benchmark: 微调模型 vs 通用模型的精度对比

### Task 6.3: 渐开线齿轮参数化
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/knowledge/templates/gear_involute.yaml`
- **AC:**
  - AC1: 标准渐开线齿廓生成（模数、齿数、压力角）
  - AC2: 齿顶圆、齿根圆、基圆精确计算
  - AC3: 齿轮参数化模板（可调模数/齿数/厚度/轴孔）
  - AC4: 替换现有矩形近似齿轮示例
- **产出:**
  - 渐开线齿轮模板
  - 齿轮参数推荐（模数系列）
- **验证:**
  - 生成的齿轮齿廓可通过几何验证
  - 3D 打印后可实际啮合

### Task 6.4: 复杂零件模板（sweep/loft）
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/knowledge/templates/`
- **AC:**
  - AC1: sweep 模板（管件、弯管）
  - AC2: loft 模板（渐变截面零件）
  - AC3: 复合特征模板（多 boolean 操作）
- **产出:**
  - 3-5 个复杂零件模板
- **验证:**
  - 模板生成的 STEP 文件几何正确

### Task 6.5: 高级可打印性优化
- **状态:** ✅ 已完成
- **标签:** [backend] [frontend]
- **范围:** `backend/core/printability.py`, 前端优化建议 UI
- **AC:**
  - AC1: 推荐打印方向（最小支撑面积）
  - AC2: 支撑策略建议（树状/线状/接触面优化）
  - AC3: 材料用量精确估算
  - AC4: 打印时间预估（基于层高和打印速度）
  - AC5: 自动修正建议（增加圆角减少应力集中等）
- **产出:**
  - 高级可打印性分析
  - 优化建议 UI
- **验证:**
  - 打印方向推荐合理性人工评估

### Task 6.6: 轮廓叠加比对
- **状态:** ✅ 已完成
- **标签:** [backend]
- **范围:** `backend/infra/render.py`, `backend/core/smart_refiner.py`
- **依赖:** Task 2.2（多视角渲染基础）
- **AC:**
  - AC1: 渲染 3D 模型的线框轮廓图
  - AC2: 与原图纸叠加（图像合成）
  - AC3: VL 对叠加图进行差异比对
- **产出:**
  - 轮廓叠加渲染 + VL prompt
- **验证:**
  - 叠加图清晰可辨差异

---

## 依赖关系总览

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5 ──→ Phase 6
  │              │            │            │            │            │
  │              │            │            │            │            ├─ Task 6.2 依赖 6.1
  │              │            │            │            │            └─ Task 6.6 依赖 2.2
  │              │            │            │            └─ Task 5.5 依赖 4.2
  │              │            │            ├─ Task 4.2 依赖 4.1 + 3.2
  │              │            │            └─ Task 4.5 依赖 1.9 + 4.3
  │              │            └─ Task 3.3 依赖 3.2
  │              ├─ Task 2.1 依赖 1.2（PipelineConfig）
  │              └─ Task 2.7 依赖 2.1-2.4
  ├─ Task 1.7 依赖 1.5 + 1.6
  ├─ Task 1.9（3D 预览）依赖 1.3 + 1.4
  └─ Task 1.10（评测前端）依赖 1.7 + 1.3
```

**跨 Phase 依赖（关键路径）：**
- Task 2.1（Best-of-N）← Task 1.2（PipelineConfig 模型）
- Task 4.2（IntentParser）← Task 3.2（ParamDefinition 定义）
- Task 6.6（轮廓叠加）← Task 2.2（多视角渲染）

Phase 间为顺序依赖（后 Phase 建立在前 Phase 基础上），Phase 内任务尽量并行。
