## Why

当前 CADPilot 的数据生命周期存在断裂：Job 结果不包含生成的 CadQuery 代码（无法复现或迭代）、用户纠偏数据虽已收集但从未用于模型改进、Benchmark 评测只有占位实现无法验证管道质量。这导致平台无法形成"生成→纠偏→学习→提升"的飞轮闭环，也无法量化质量改进效果。

## What Changes

- **CadQuery 代码持久化**：Job 结果中保存生成的 Python 代码，支持查看、复制、再编辑
- **版本链关联**：新增 `parent_job_id` 字段，支持 text 类型"改参数重生成"时保留版本溯源关系
- **V2 Pipeline 返回值增强**：修改管道返回签名，暴露生成的代码字符串
- **Benchmark 实装**：`_run_single()` 集成实际 V2 管道调用，输出量化评测报告
- **纠偏数据清洗**：从 UserCorrection 记录中过滤无效数据、构建训练三元组
- **纠偏统计 API**：按 field_path / part_type 统计修正频率
- **SFT 微调管道**：纠偏数据 → JSONL → LoRA 微调脚本，形成数据飞轮闭环

## Capabilities

### New Capabilities
- `code-persistence`: Job 结果持久化 CadQuery 生成代码 + parent_job_id 版本链
- `benchmark-runner`: Benchmark 评测实装，集成实际管道调用并输出评测报告
- `correction-analytics`: 纠偏数据清洗、统计 API、频率分析
- `sft-pipeline`: 纠偏数据 → JSONL 训练集 → LoRA 微调脚本

### Modified Capabilities
- `langgraph-job-orchestration`: CadJobState 新增 `generated_code` 和 `parent_job_id` 字段

## Impact

- **后端模型**：`backend/db/models.py` — JobModel 新增字段 + SQL 迁移脚本
- **管道节点**：`backend/graph/nodes/generation.py` — 保存生成代码到 state
- **V2 管道**：`cadpilot/pipeline.py` — 修改返回值暴露代码字符串
- **API 层**：`backend/api/v1/jobs.py` — Fork API + 纠偏统计 API
- **评测系统**：`backend/benchmark/runner.py` — 实装 _run_single()
- **训练脚本**：新建 `scripts/data/` + `scripts/training/` 目录
