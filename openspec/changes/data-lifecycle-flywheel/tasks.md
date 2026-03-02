## 1. 代码持久化 + 版本链 [backend]

- [ ] 1.1 CadJobState 新增 `generated_code` 和 `parent_job_id` 字段
- [ ] 1.2 JobModel 新增 `generated_code` (Text) 和 `parent_job_id` (String) 列，STATE_TO_ORM_MAPPING 更新
- [ ] 1.3 generate_step_text_node 保存 SpecCompiler 返回的代码到 state["generated_code"]
- [ ] 1.4 generate_step_drawing_node 保存 V2 管道生成的代码到 state["generated_code"]
- [ ] 1.5 finalize_node 持久化 generated_code 和 parent_job_id 到 JobModel
- [ ] 1.6 GET /api/v1/jobs/{id} 响应中包含 generated_code 和 parent_job_id
- [ ] 1.7 POST /api/v1/jobs 支持 parent_job_id 参数，create_job_node 写入 state
- [ ] 1.8 编写 test_code_persistence.py 测试代码保存和版本链

## 2. 输出归档结构 [backend]

- [ ] 2.1 LocalFileStorage.save() 新增可选 subdir 参数，更新 URL 路径生成
- [ ] 2.2 create_job_node 上传图片时使用 subdir="input"
- [ ] 2.3 generation 节点 STEP 文件使用 subdir="intermediate"，code.py 使用 subdir="output"
- [ ] 2.4 convert_preview_node GLB 使用 subdir="output"
- [ ] 2.5 analyze_dfam_node DfAM GLB 使用 subdir="output"
- [ ] 2.6 编写 test_file_storage.py 测试 subdir 归档逻辑
- [ ] 2.7 更新 StaticFiles mount 和 /outputs/ 路由以支持子目录

## 3. Benchmark 实装 [backend]

- [ ] 3.1 BenchmarkCase 扩展支持 input_type 和 input_text 字段
- [ ] 3.2 _run_single() 实装：drawing case 调用 generate_step_from_2d_cad_image
- [ ] 3.3 _run_single() 实装：text case 调用 generate_step_v2
- [ ] 3.4 添加参数精度比对逻辑（expected_spec vs 实际 DrawingSpec）
- [ ] 3.5 添加包围盒匹配验证（提取 STEP bbox vs expected_bbox）
- [ ] 3.6 创建 benchmarks/v1/ 下至少 3 个 drawing case JSON + 2 个 text case JSON
- [ ] 3.7 编写 test_benchmark_runner.py 测试 _run_single 和 metrics 聚合

## 4. 纠偏数据清洗 + 统计 API [backend]

- [ ] 4.1 创建 scripts/data/clean_corrections.py — 读 DB 纠偏记录、过滤无效、输出 JSONL
- [ ] 4.2 添加 Job 关联逻辑：join correction → job intent/drawing_spec 构建训练三元组
- [ ] 4.3 创建 GET /api/v1/corrections/stats 端点 — top_fields 聚合
- [ ] 4.4 支持 ?part_type= 过滤和 ?group_by=week 时间趋势
- [ ] 4.5 编写 test_correction_analytics.py 测试清洗逻辑和统计 API

## 5. SFT 微调管道 [scripts]

- [ ] 5.1 创建 scripts/training/sft_formatter.py — corrections_clean.jsonl → Chat JSONL
- [ ] 5.2 添加 system prompt 模板，包含 part_type 上下文
- [ ] 5.3 实现 train/eval 集 90/10 确定性拆分
- [ ] 5.4 创建 scripts/training/sft_config.py — LoRA 超参数配置
- [ ] 5.5 编写 test_sft_formatter.py 测试格式转换和拆分逻辑

## 6. 集成验证

- [ ] 6.1 全量测试通过 + TypeScript 类型检查
- [ ] 6.2 端到端验证：创建 Job → 查看 generated_code → Fork → 查看 parent_job_id
- [ ] 6.3 Benchmark dry-run：至少 1 个 case 完整跑通
