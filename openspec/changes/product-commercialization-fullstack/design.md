## Context

cad3dify 的 V3 架构已建立精密建模（参数化模板 + LLM fallback）和有机路径（Tripo3D/Hunyuan3D + mesh 后处理）两条管道，但多个已实现模块未串入主管道：PrintabilityChecker（壁厚/悬垂/材料/成本）、OCR 辅助层、IntentParser（LLM 意图解析）。图纸路径缺少 HITL 暂停点，Job 存储为纯内存 dict。

详细技术设计见 brainstorming 产出：`docs/plans/2026-02-28-product-commercialization-fullstack-design.md`。本文档聚焦架构决策和跨模块协调。

## Goals / Non-Goals

**Goals:**
- 将 PrintabilityChecker 串入精密建模和有机路径管道，每次生成自动输出可打印性报告
- 为图纸路径添加 HITL 确认流，含免责声明和用户修正数据收集
- 接入 PaddleOCR，与 VLM 结果融合提升工程图纸识别精度
- 用 IntentParser 替换 keyword 匹配实现智能模板路由
- 引入 SQLite 持久化层，所有 Job/Spec/用户修正数据持久化
- 新增零件库历史页面和参数实时预览 API
- 补全有机路径 3MF 导出

**Non-Goals:**
- 用户认证/多租户系统（user_id 预留字段但不实现认证流程）
- PostgreSQL 迁移（SQLite 当前阶段够用）
- 微调训练启动（等数据积累）
- 车间直连 / G-Code / OctoPrint 集成
- Benchmark 系统完善（_run_single 仍是 TODO）

## Decisions

### D1: 实施顺序——管道串联优先（方案 A）

**选择**：P0 管道串联 → P1 智能层 → P2 数据基础设施

**备选**：方案 B（数据底座优先，先建 SQLite 再串管道）

**理由**：PrintabilityChecker 接入只需加 API 路由，1-2 天可见效。HITL 确认流是工业客户法务刚需。先产出可演示价值，再建基础设施。数据库较晚引入的风险通过 JSON 文件暂存缓解。

### D2: 数据库选型——SQLite（含 aiosqlite 稳定性措施）

**选择**：SQLite + SQLAlchemy 2.0 + aiosqlite + Alembic

**备选**：
- PostgreSQL（主项目 agentic-runtime 使用，但需额外部署）
- MongoDB（文档型适合 JSON spec，但团队无经验）

**理由**：零部署成本、单文件分发、开发简单。SQLAlchemy 的 ORM 抽象层使后期迁移到 PostgreSQL 只需改连接字符串。JSON1 扩展支持复杂的 DrawingSpec/IntentSpec 存储。

**aiosqlite 稳定性**（Gemini 审查 P1：SQLAlchemy #13039 连接挂起问题）：
- 钉死 `aiosqlite>=0.20.0`（包含修复）
- engine 创建时设置 `connect_args={"timeout": 30}`（busy timeout）
- 使用 `pool_pre_ping=True` 检测断开连接

### D3: OCR 引擎——PaddleOCR

**选择**：PaddleOCR（本地部署，CPU 推理）

**备选**：
- Tesseract（中文弱，工程图标注识别差）
- Qwen-VL OCR prompt（无新依赖但精度不稳定、延迟 2s+）
- Google Cloud Vision（付费 API）

**理由**：工程图纸中 `φ50`、`R15`、`6×M8`、`50±0.1` 等标注格式，PaddleOCR 识别率最高。本地 CPU 推理 ~200ms/图，零 API 成本。通过已有的 `ocr_fn: Callable` 依赖注入接口接入，侵入性最低。推荐使用 PP-OCRv5（Gemini 审查建议）。

### D4: PrintabilityChecker 触发策略——自动触发

**选择**：生成完成后自动触发，结果嵌入 SSE completed 事件

**备选**：
- 用户手动触发（需额外 API 调用）
- 后台异步（完成后不立即可见）

**理由**：工业客户期望每次生成都带检查报告，这是"专业工具"而非"玩具"的标志。自动触发 + SSE 推送让报告与 3D 模型同时呈现，零额外操作。

### D5: geometry_info 提取——双路径策略

**选择**：精密建模从 STEP 提取（OCP 几何查询），有机路径从 mesh 提取（trimesh 分析）

**理由**：精密建模输出 STEP（B-Rep，精确几何），有机路径输出 mesh（三角网格，近似几何）。两种格式的几何信息提取方法不同，需要统一为 `geometry_info` dict 后交给 PrintabilityChecker。

### D6: HITL 数据收集——user_corrections 独立表

**选择**：用户每次修正 DrawingSpec 的字段，记录为 `(job_id, field_path, original_value, corrected_value)` 元组

**理由**：这是数据飞轮（方向 C）的核心资产。`[图片, 原始spec, 修正spec]` 三元组直接用于 VLM 微调。独立表便于后期批量导出训练数据，不污染 Job 主表。

### D7: 实时预览——后端 API + 缓存（分级响应时间）

**选择**：`POST /preview/parametric` → 模板引擎→CadQuery→GLB（draft quality），分级响应时间目标

**备选**：
- 前端近似预览（Three.js 基本几何体组合）— 快但不精确
- WebAssembly CadQuery — 技术不成熟

**理由**：后端预览使用真实 CadQuery 引擎，输出与最终生成一致。draft quality（减面 70%）+ 参数缓存。debounce 300ms 避免频繁调用。

**分级响应时间**（Gemini 审查修正：CadQuery 对复杂零件 <1s 不现实）：
- 简单零件（<10 features）：< 1s
- 中等零件（10-30 features）：< 3s
- 复杂零件（>30 features）：< 5s → 超时返回 408

### D8: 图纸路径管道拆分——Stage 1 / Stage 2-4 分离

**选择**：将 `generate_step_v2()` 拆分为 `analyze_drawing()`（Stage 1）和 `generate_from_drawing_spec()`（Stage 1.5-4），SSE 流分为两段

**备选**：
- 在 pipeline.py 内部加 callback 暂停点（侵入性大、难测试）
- 前端模拟暂停（Stage 1-4 全跑，前端拦截结果先展示 spec）— 浪费算力

**理由**：（Codex + Gemini 共同审查 P1）当前 `generate_step_v2()` 将 Stage 1（VL 读图）到 Stage 4（SmartRefiner）作为单次调用运行，无法在 Stage 1 完成后暂停等待用户确认。HITL 确认流要求：Stage 1 完成 → 返回 DrawingSpec → 用户确认/修改 → Stage 2-4 继续。拆分为两个独立函数是最干净的方案，每段各自有 SSE 流。

## Risks / Trade-offs

**[R1] PaddleOCR 包体较大（~30MB）** → 仅影响首次部署/Docker 镜像大小。可通过 optional dependency group 管理，不安装时自动降级为纯 VLM 模式。

**[R2] SQLite 并发写入限制** → 单写者模型。当前单 uvicorn worker 场景下无问题。多 worker 部署时需切换到 PostgreSQL（Alembic 迁移脚本已就绪）。

**[R3] CadQuery 执行超时导致预览 API 慢** → 设置 5s 硬超时。复杂零件（>50 个特征）可能超时，返回"预览不可用，请直接生成"。长期可引入预编译/缓存策略优化。

**[R4] HITL 暂停导致图纸路径体验变慢** → 用户需要额外确认步骤。但工业客户更重视准确性而非速度。提供"信任 AI 跳过确认"选项给高频用户。

**[R5] P0 阶段 HITL 数据暂存于 JSON 文件（强制）** → 数据库在 P2 引入前，用户修正数据**必须**持久化到 `backend/data/corrections/{job_id}.json`，不接受仅内存暂存。JSON 文件在 P2 完成后批量导入数据库。（Gemini 审查 P1：HITL 修正数据是数据飞轮核心资产，进程重启丢失不可接受）

**[R6] IntentParser 依赖 LLM 可用性** → LLM 不可用时自动降级为 keyword 匹配（保留原有 `_match_template()` 作为 fallback）。
