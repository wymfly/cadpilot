## Why

当前 CADPilot 的数据生命周期存在断裂：Job 结果不包含生成的 CadQuery 代码（无法复现或迭代）、用户纠偏数据虽已收集但从未用于模型改进、Benchmark 评测只有占位实现无法验证管道质量、输出文件缺乏归档结构。这导致平台无法形成"生成→纠偏→学习→提升"的飞轮闭环，也无法量化质量改进效果。

## What Changes

- **CadQuery 代码持久化**：Job 结果中保存生成的 Python 代码，支持查看、复制、再编辑
- **版本链关联**：新增 `parent_job_id` 字段，支持"改参数重生成"时保留版本溯源关系
- **输出归档结构**：outputs/{job_id}/ 分 input/intermediate/output 三层子目录
- **Benchmark 实装**：`_run_single()` 集成实际 V2 管道调用，输出量化评测报告
- **纠偏数据清洗**：从 UserCorrection 记录中过滤无效数据、构建训练三元组
- **纠偏统计 API**：按 field_path / part_type 统计修正频率，支持时间趋势查询
- **SFT 微调管道**：纠偏数据 → JSONL → LoRA 微调脚本，形成数据飞轮闭环

## Capabilities

### New Capabilities
- `code-persistence`: Job 结果持久化 CadQuery 生成代码 + parent_job_id 版本链
- `output-archive`: 输出文件归档结构（input/intermediate/output 三层目录）
- `benchmark-runner`: Benchmark 评测实装，集成实际管道调用并输出评测报告
- `correction-analytics`: 纠偏数据清洗、统计 API、频率/趋势分析
- `sft-pipeline`: 纠偏数据 → JSONL 训练集 → LoRA 微调脚本

### Modified Capabilities
- `langgraph-job-orchestration`: Job 状态新增 `generated_code` 和 `parent_job_id` 字段，generation 节点需保存代码到 state

## Impact

- **后端模型**：`backend/db/models.py` — JobModel 新增字段 + Alembic 迁移
- **管道节点**：`backend/graph/nodes/generation.py` — 保存生成代码到 state
- **API 层**：`backend/api/v1/jobs.py` — Fork 重生成 API + 纠偏统计 API
- **文件存储**：`backend/db/file_storage.py` — 输出归档重组
- **评测系统**：`backend/benchmark/runner.py` — 实装 _run_single()
- **训练脚本**：新建 `scripts/data/` + `scripts/training/` 目录
- **前端**：Job 详情页展示代码 + 版本链（可选，优先级低）
