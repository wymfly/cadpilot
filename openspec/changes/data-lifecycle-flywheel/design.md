## Context

CADPilot 已具备完整的生成管道（text/drawing/organic → STEP → GLB），但数据生命周期存在多个断裂点：

1. **代码不可追溯**：generation 节点生成 CadQuery 代码后仅写入 STEP 文件，代码本身不持久化，无法查看、复制或迭代。
2. **版本无关联**："改参数重生成"无法追溯原始 Job，缺少 parent_job_id 链。
3. **评测占位**：`BenchmarkRunner._run_single()` 返回全 False 占位，无法验证管道质量。
4. **纠偏数据沉睡**：`UserCorrectionModel` 已收集纠偏记录（JSON + DB 双写），但无清洗、统计或训练管道。

当前关键资产：
- `backend/db/models.py` — `JobModel` + `UserCorrectionModel` ORM
- `backend/graph/state.py` — `CadJobState` TypedDict
- `backend/benchmark/runner.py` — 框架完备（metrics/reporter/CLI），仅缺 `_run_single`
- `backend/data/corrections/*.json` — 已积累纠偏数据

## Goals / Non-Goals

**Goals:**
- Job 结果包含完整 CadQuery Python 代码，支持查看和复制
- 支持 text 类型 Job 的 Fork 重生成并保留版本链关系
- Benchmark 可实际执行并输出量化报告
- 纠偏数据可清洗、统计
- SFT 微调管道从纠偏数据生成训练集

**Non-Goals:**
- 用户系统 / 多租户（M5 范围外）
- 前端代码编辑器 / Monaco 集成（远期任务）
- 实际执行 LoRA 训练（只产出训练脚本和配置，不在线训练）
- 纠偏仪表盘前端 UI（本期仅 API）
- Drawing / Organic 类型 Fork（初始仅 text）
- 输出目录重组（保持现有扁平结构，避免路径耦合破坏）

## Decisions

### D1: CadQuery 代码保存位置 — CadJobState + JobModel + 文件

**选择**：`CadJobState` 新增 `generated_code: str | None`，generation 节点将代码文本写入 state，finalize 时持久化到 `JobModel.generated_code` 列 + `outputs/{job_id}/code.py` 文件。

**备选**：仅存文件。
**理由**：DB 列支持 API 查询免文件 I/O；文件用于用户下载和 benchmark 复现。代码量通常 <10KB。

### D2: parent_job_id 版本链 — text 类型单层外键

**选择**：`JobModel` 新增 `parent_job_id: str | None` 字段。仅 text 类型 Job 支持 Fork（POST /api/v1/jobs 传入 parent_job_id）。Drawing fork 需图片复制，Organic fork 用独立 OrganicJobModel，均延后。

**备选**：全类型 Fork。
**理由**：text fork 最简单（继承 input_text，无文件引用），先做最小可用版本。

### D3: Drawing 代码捕获 — 修改 V2 pipeline 返回值

**选择**：修改 `cadpilot.pipeline` 中 `_run_generate_from_spec()` 使其返回 `(step_path, code_text)` 元组，而非仅写文件无返回。`generate_step_drawing_node` 从返回值中提取代码写入 state。

**备选**：从 STEP 文件反推代码（不可行）。
**理由**：当前 pipeline 内部 `CodeGeneratorChain` 已生成代码字符串，只是没暴露。修改返回签名是最小改动。

### D4: Benchmark 集成策略

**选择**：
- Drawing cases：`_run_single()` 调用 `generate_step_from_2d_cad_image()`（V2 管道）
- Text cases：通过 SpecCompiler 同步调用（模板匹配 + LLM fallback）
- 所有管道调用包装在 `asyncio.to_thread()` 中避免阻塞事件循环
- 失败分类：先映射异常到关键字指标（`compile_error=True` 等），再调 `classify_failure(**indicators)`

**备选**：走 LangGraph DAG。
**理由**：Benchmark 测质量不测 HITL 流程。直接调管道函数最快。

### D5: 纠偏数据清洗 — 独立 CLI 脚本 + 关联容错

**选择**：`scripts/data/clean_corrections.py` — 读 DB `user_corrections` 表，left join `jobs` 表获取 intent/drawing_spec。

**关键容错**：`UserCorrectionModel` 可能引用未持久化的 drawing 流 Job（注释已说明）。清洗脚本 JOIN 失败时跳过该记录并记 warning，不崩溃。

**备选**：集成到 API。
**理由**：清洗是批处理任务，CLI 脚本更灵活。

### D6: DB 迁移策略 — ALTER TABLE SQL 脚本

**选择**：提供 `scripts/migrations/001_add_code_and_parent.sql` 手动迁移脚本。`create_all()` 仅对全新 DB 生效；已有 DB 需执行迁移脚本。

**备选**：Alembic。
**理由**：当前仅 2 个新列，Alembic 引入过重。SQL 脚本 + 文档足够。未来列变更增多时再引入 Alembic。

```sql
ALTER TABLE jobs ADD COLUMN generated_code TEXT;
ALTER TABLE jobs ADD COLUMN parent_job_id VARCHAR(64);
```

## Risks / Trade-offs

- **[管道返回值修改]** 修改 `_run_generate_from_spec` 返回签名是跨模块变更。需确保所有调用点适配 → 影响范围已验证仅 `generate_step_drawing_node`。
- **[Benchmark 耗时]** V2 管道单个 case ~30-60s/case，必须用 asyncio.to_thread 避免死锁。5 个 case 约 5min → 可接受。
- **[纠偏数据量]** 当前 <100 条。SFT 训练数据不足 → 脚本先跑通，训练效果后期评估。
- **[未持久化 Job]** Drawing 流的纠偏关联可能丢失 → 清洗脚本容错处理。
