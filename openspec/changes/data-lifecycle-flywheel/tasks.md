## 0. 前置：V2 Pipeline 返回值修改 [backend]

- [ ] 0.1 修改 `cadpilot/pipeline.py` 中 `_run_generate_from_spec()` 返回 `(step_path, code_text)` 元组
- [ ] 0.2 修改 `generate_step_from_2d_cad_image()` 适配新返回值
- [ ] 0.3 创建 `scripts/migrations/001_add_code_and_parent.sql` 迁移脚本
- [ ] 0.4 确保 `create_all()` 新 DB 自动包含新列

## 1. 代码持久化 + 版本链 [backend]

- [ ] 1.1 CadJobState 新增 `generated_code` 和 `parent_job_id` 字段
- [ ] 1.2 JobModel 新增 `generated_code` (Text) 和 `parent_job_id` (String) 列
- [ ] 1.3 STATE_TO_ORM_MAPPING 更新，添加新字段映射
- [ ] 1.4 generate_step_text_node 保存 SpecCompiler 返回的代码到 state["generated_code"]
- [ ] 1.5 generate_step_drawing_node 从 pipeline 新返回值提取代码到 state["generated_code"]
- [ ] 1.6 finalize_node 持久化 generated_code 和 parent_job_id 到 JobModel（含失败场景保留 code）
- [ ] 1.7 generation 节点同时写 `outputs/{job_id}/code.py` 文件
- [ ] 1.8 JobDetailResponse Pydantic 模型新增 generated_code + parent_job_id + child_job_ids
- [ ] 1.9 GET /api/v1/jobs/{id} 实现 child_job_ids 查询（按 parent_job_id 过滤）
- [ ] 1.10 POST /api/v1/jobs 支持 parent_job_id 参数（仅 text 类型，其他类型返回 400）
- [ ] 1.11 create_job_node 将 parent_job_id 写入 state
- [ ] 1.12 编写 test_code_persistence.py 测试代码保存、版本链、fork 限制

## 2. Benchmark 实装 [backend]

- [ ] 2.1 BenchmarkCase 扩展支持 input_type 和 input_text 字段
- [ ] 2.2 _run_single() 实装：drawing case 通过 asyncio.to_thread 调用 generate_step_from_2d_cad_image
- [ ] 2.3 _run_single() 实装：text case 通过 asyncio.to_thread 调用 SpecCompiler
- [ ] 2.4 添加异常 → classify_failure 关键字指标映射逻辑
- [ ] 2.5 添加参数精度比对逻辑（expected_spec vs 实际 DrawingSpec，10% 容差）
- [ ] 2.6 添加包围盒匹配验证（提取 STEP bbox vs expected_bbox，15% 容差）
- [ ] 2.7 创建 benchmarks/v1/ 下至少 3 个 drawing case JSON + 2 个 text case JSON
- [ ] 2.8 编写 test_benchmark_runner.py 测试 _run_single 和 metrics 聚合

## 3. 纠偏数据清洗 + 统计 API [backend]

- [ ] 3.1 创建 scripts/data/clean_corrections.py — 读 DB 纠偏记录、过滤无效、输出 JSONL
- [ ] 3.2 添加 Job 关联逻辑：left join jobs 表获取 intent/drawing_spec，未关联记录跳过并 warning
- [ ] 3.3 创建 GET /api/v1/corrections/stats 端点 — top_fields 聚合（最多 20 条）
- [ ] 3.4 支持 ?part_type= 过滤参数
- [ ] 3.5 编写 test_correction_analytics.py 测试清洗逻辑和统计 API

## 4. SFT 微调管道 [scripts]

- [ ] 4.1 创建 scripts/training/sft_formatter.py — corrections_clean.jsonl → Qwen Chat JSONL
- [ ] 4.2 添加 system prompt 模板，包含 part_type 上下文
- [ ] 4.3 实现 train/eval 集 90/10 确定性拆分（seeded random）
- [ ] 4.4 创建 scripts/training/sft_config.py — LoRA 超参数配置（rank=16, alpha=32, lr=2e-4）
- [ ] 4.5 编写 test_sft_formatter.py 测试格式转换和拆分逻辑

## 5. 集成验证

- [ ] 5.1 全量测试通过 + TypeScript 类型检查
- [ ] 5.2 端到端验证：创建 text Job → 查看 generated_code → Fork → 查看 parent_job_id + child_job_ids
- [ ] 5.3 Benchmark dry-run：至少 1 个 case 完整跑通
