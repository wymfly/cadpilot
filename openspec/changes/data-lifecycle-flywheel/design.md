## Context

CADPilot 已具备完整的生成管道（text/drawing/organic → STEP → GLB），但数据生命周期存在多个断裂点：

1. **代码不可追溯**：generation 节点生成 CadQuery 代码后仅写入 STEP 文件，代码本身不持久化，无法查看、复制或迭代。
2. **版本无关联**："改参数重生成"无法追溯原始 Job，缺少 parent_job_id 链。
3. **输出平铺**：`outputs/{job_id}/` 下所有文件平铺，无结构化归档。
4. **评测占位**：`BenchmarkRunner._run_single()` 返回全 False 占位，无法验证管道质量。
5. **纠偏数据沉睡**：`UserCorrectionModel` 已收集纠偏记录（JSON + DB 双写），但无清洗、统计或训练管道。

当前关键资产：
- `backend/db/models.py` — `JobModel` + `UserCorrectionModel` ORM
- `backend/graph/state.py` — `CadJobState` TypedDict
- `backend/benchmark/runner.py` — 框架完备（metrics/reporter/CLI），仅缺 `_run_single`
- `backend/data/corrections/*.json` — 已积累纠偏数据

## Goals / Non-Goals

**Goals:**
- Job 结果包含完整 CadQuery Python 代码，支持查看和复制
- 支持 Fork 重生成并保留版本链关系
- 输出文件按 input/intermediate/output 分层归档
- Benchmark 可实际执行并输出量化报告
- 纠偏数据可清洗、统计、可视化
- SFT 微调管道从纠偏数据生成训练集

**Non-Goals:**
- 用户系统 / 多租户（M5 范围外）
- 前端代码编辑器 / Monaco 集成（远期任务）
- 实际执行 LoRA 训练（只产出训练脚本和配置，不在线训练）
- 纠偏仪表盘前端 UI（本期仅 API）

## Decisions

### D1: CadQuery 代码保存位置 — 存入 CadJobState + JobModel

**选择**：在 `CadJobState` 新增 `generated_code: str | None` 字段，generation 节点将代码文本写入 state，finalize 时持久化到 `JobModel.generated_code` 列。

**备选**：仅存文件（`outputs/{job_id}/code.py`）。
**理由**：代码是核心资产，需支持 API 查询，DB 列 + 文件双存更可靠。代码量通常 <10KB，DB 存储无压力。

### D2: parent_job_id 版本链 — 单层外键

**选择**：`JobModel` 新增 `parent_job_id: str | None` 字段。Fork 时前端传入 parent_job_id，后端创建新 Job 时设置关联。

**备选**：多层链式（parent → grandparent）递归查询。
**理由**：当前迭代深度不超过 2-3 层，单层外键够用。API 按 parent_job_id 查可得直接子版本。

### D3: 输出归档结构 — 写时分层

**选择**：`LocalFileStorage.save()` 接受可选 `subdir` 参数。各节点按约定写入：
- `input/` — 上传图片
- `intermediate/` — 中间产物（STEP、分析结果）
- `output/` — 最终交付物（GLB、DfAM GLB）

**备选**：后处理归档脚本（异步重组）。
**理由**：写时分层零运行时开销，且对已有代码改动最小（仅改 save 调用参数）。

### D4: Benchmark 集成策略 — 复用现有 V2 管道函数

**选择**：`_run_single()` 调用 `cadpilot.pipeline.generate_step_from_2d_cad_image()`，不走 LangGraph。

**备选**：走完整 LangGraph DAG（需模拟 HITL 确认）。
**理由**：Benchmark 测的是 VL+Coder 质量，不是 HITL 流程。直接调 V2 管道函数最简单、最快。后续可增加 LangGraph 路径。

### D5: 纠偏数据清洗 — 独立 CLI 脚本

**选择**：`scripts/data/clean_corrections.py` — 读 DB `user_corrections` 表，过滤无效记录，输出 JSONL 训练三元组。

**备选**：集成到 API（实时清洗）。
**理由**：清洗是批处理任务，不需要实时。CLI 脚本可 cron 调度，且便于调试。

### D6: SFT 训练集格式 — Qwen Chat JSONL

**选择**：每条记录格式：
```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "<spec>"}, {"role": "assistant", "content": "<corrected_code>"}]}
```

**理由**：与 Qwen2.5-Coder 的 Chat SFT 格式兼容，支持 LoRA 微调。

## Risks / Trade-offs

- **[Alembic 迁移]** JobModel 新增列需 Alembic migration。当前项目未用 Alembic → 使用 SQLAlchemy `create_all()` 自动建列，加文档说明首次升级需清 DB 或手动 ALTER。
- **[Benchmark 耗时]** V2 管道单个 case 调用 VL + Coder 模型，~30-60s/case。5 个 case 约 5min → 可接受。
- **[纠偏数据量]** 当前纠偏记录 <100 条，SFT 训练数据不足 → 脚本先跑通，训练效果后期评估。
- **[代码字段大小]** CadQuery 代码通常 <10KB，SQLite TEXT 列无大小限制 → 无风险。
