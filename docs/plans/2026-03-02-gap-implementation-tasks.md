# CADPilot 差距修复实施任务清单

> 来源：`docs/plans/ai-3d-printing-strategy/2026-03-01-multi-perspective-gap-synthesis.md`
> 日期：2026-03-02
> 分析视角：Claude Opus + 4 Agent Team + Codex (GPT) + Gemini 2.5 Pro

---

## 执行顺序与依赖关系

```
M1（安全+串联）→ M2（SpecCompiler）→ M3（白盒化UI）
                                    → M4（DfAM）     ← 可与 M3 并行
                                    → M5（数据飞轮）  ← 依赖 M1 的持久化修复
```

---

## M1：安全加固 + 代码孤岛串联

- **状态**：待实施
- **优先级**：P0
- **模式**：Mode 1 短路径（目标清晰，修复已有代码）
- **工作量**：4-6 天
- **依赖**：无
- **解锁**：M2, M3, M4, M5

### 范围

| 子项 | 来源 | 涉及文件 | 说明 |
|------|------|---------|------|
| eval() → AST 安全评估 | Codex P0, Gemini P1 | `backend/core/template_engine.py:72` | 约束校验使用 `eval()` → 远程代码执行风险。改用 `ast.literal_eval` 或声明式约束 |
| 模板 API 认证中间件 | Codex P0 | `backend/api/v1/templates.py` | 模板 CRUD API 无认证保护，任何人可创建/修改模板 |
| MemorySaver → 持久化 checkpointer | Codex P1 | `backend/graph/builder.py:100` | LangGraph 用内存 checkpointer，进程重启丢失 HITL 状态 |
| pipeline_config 执行实装 | Codex P1 | `backend/api/v1/jobs.py:55,213` | API 接收 pipeline_config 但执行时忽略（"假功能"） |
| 前后端枚举大小写修复 | Codex P1 | `frontend/.../DrawingSpecForm:24`, `backend/knowledge/part_types.py:11` | 前端大写 ROTATIONAL vs 后端可能小写 |
| TokenTracker 串入 LangGraph | data-analyst P2 | `backend/infra/token_tracker.py`（未被引用） | 代码完成但从未调用，串入各 LLM 节点 |
| CostOptimizer 串入管道 | data-analyst P2 | `backend/core/cost_optimizer.py`（未被引用） | 结果缓存 + 模型降级策略，代码完成未使用 |
| PrintabilityChecker 拦截能力 | arch-analyst P2 | `backend/graph/nodes/postprocess.py:67` | printable=False 时仅 warning 不中断，需赋予拦截权 |

### 验收标准

- [ ] `template_engine.py` 中零 `eval()` 调用
- [ ] 模板 API 需认证才能写入（GET 可匿名）
- [ ] LangGraph checkpointer 支持跨进程重启恢复 HITL 状态
- [ ] `pipeline_config` 中的 `llm_model` / `temperature` 影响实际 LLM 调用
- [ ] 前后端 PartType 枚举值一致
- [ ] Job 结果中包含 `token_stats` 字段
- [ ] `printable=False` + error 级 issue 时 Job 状态为 `failed`
- [ ] 所有现有测试通过

---

## M2：SpecCompiler + 精密路径架构重构

- **状态**：待实施
- **优先级**：P0
- **模式**：Mode 2 (OpenSpec)
- **工作量**：7-10 天
- **依赖**：无（但建议 M1 先完成安全修复）
- **解锁**：M10

### 范围

| 子项 | 来源 | 涉及文件 | 说明 |
|------|------|---------|------|
| SpecCompiler 统一调度器 | 6/6 共识 | 新建 `backend/core/spec_compiler.py` | part_type → 模板优先 → LLM fallback 的统一入口 |
| text-path LLM fallback | Codex P0 | `backend/graph/nodes/generation.py:87` | 模板 miss 时 hard-fail → 改为自动降级到 Coder 模型 |
| IntentParser.part_type → TemplateEngine.find_matches | arch-analyst P1 | `backend/graph/nodes/analysis.py:78-98` | 替换 keyword 匹配为语义路由 |
| DrawingSpec IR 规范化 | arch-analyst P2 | `backend/knowledge/part_types.py:101-148` | overall_dimensions 标准化键名，Feature.spec 去除 dict fallback |
| 拦截器注册表 | arch-analyst P2 | `backend/graph/builder.py:33-83` | 节点动态注册机制，支持插入 Watermark/ThermalAnalysis 等步骤 |
| 后加工推荐引擎 | Codex P2, innovation P2 | `backend/models/job.py:43`（recommendations 字段未填充） | 基于 printability 结果推荐 NX/Magics/Oqton 操作 |

### 验收标准

- [ ] `SpecCompiler.compile(spec)` 统一入口可用
- [ ] text-path 模板未匹配时自动降级到 LLM 代码生成
- [ ] DrawingSpec.overall_dimensions 使用规范化键名 schema
- [ ] 新步骤可通过注册表插入管道而无需修改 builder.py
- [ ] Job 结果中 `recommendations` 字段包含后加工建议

---

## M3：白盒化 UI — SSE + 看板 + Reasoning

- **状态**：待实施
- **优先级**：P1
- **模式**：Mode 1 完整路径（需 brainstorming 确定交互方案）
- **工作量**：7-10 天
- **依赖**：T4(SSE) 是 T5(看板) 的前提，内部串行

### 范围

| 子项 | 来源 | 涉及文件 | 说明 |
|------|------|---------|------|
| SSE 事件标准化 | arch-analyst P2 | `backend/graph/nodes/*.py`, `backend/api/v1/events.py` | 统一 `node.started/completed` 事件对，添加 `elapsed_ms` + `decision` 字段 |
| @timed_node 装饰器 | arch-analyst 建议 | `backend/graph/nodes/` | 自动计算节点耗时并附加到事件 payload |
| Reasoning Trace 后端 | ux-analyst P2 | 各管道节点 | 关键决策点添加结构化 reasoning（策略匹配、模板选择、校验结果） |
| ReasoningCard 前端组件 | ux-analyst P2 | 新建 `frontend/src/components/ReasoningCard/` | 折叠面板展示 AI 推理链 |
| ReactFlow DAG 看板 | ux-analyst P1 | 替换 `frontend/src/components/PipelineProgress/` | 可交互节点图：点击回溯、分支可视化、每节点耗时 |
| 节点回溯面板 | ux-analyst P1 | 新建 | 点击已完成节点 → 加载该阶段输入/输出/决策数据 |

### 验收标准

- [ ] 每个管道节点 dispatch `node.started` 和 `node.completed` 事件，含 `elapsed_ms`
- [ ] 至少 3 个关键节点（intent_parse / template_match / printability）有 reasoning 数据
- [ ] 前端看板支持分支可视化（精密 vs 有机路径）
- [ ] 点击已完成节点可查看该阶段的输入/输出/决策解释
- [ ] 每个节点独立显示耗时

---

## M4：DfAM 真实化 + 3D 热力图

- **状态**：待实施
- **优先级**：P0
- **模式**：Mode 2 (OpenSpec)
- **工作量**：7-10 天
- **依赖**：无

### 范围

| 子项 | 来源 | 涉及文件 | 说明 |
|------|------|---------|------|
| 顶点级壁厚计算 | Gemini P0 | `backend/core/geometry_extractor.py:43`, `backend/core/printability.py:139` | 用 SDF/Ray-casting 计算每个网格顶点的壁厚值 |
| 顶点级悬垂角计算 | Gemini P0 | 同上 | 计算面法线与打印方向的夹角 |
| GLB vertex color 编码 | ux-analyst 建议 | `backend/core/format_exporter.py` 或新模块 | 将风险值 [0,1] 编码到 GLB 顶点颜色（绿→黄→红） |
| Three.js ShaderMaterial 热力图 | ux-analyst P1 | `frontend/src/components/Viewer3D/index.tsx` | 自定义着色器根据顶点颜色渲染热力图 |
| DfAM 视图切换 | ux-analyst 建议 | `frontend/src/components/Viewer3D/ViewControls.tsx` | 工具栏增加"DfAM 视图"开关 |
| PrintReport ↔ Viewer3D 联动 | ux-analyst P1 | `frontend/src/components/PrintReport/` | issue 项点击 → 3D 视图旋转到对应区域 |

### 验收标准

- [ ] geometry_extractor 输出每个顶点的壁厚和悬垂角数据
- [ ] GLB 文件包含 vertex color attribute（风险热力值）
- [ ] Viewer3D 支持 DfAM 热力图渲染模式
- [ ] PrintReport 中的 issue 可点击联动到 3D 视图对应位置
- [ ] 壁厚 < 最小值的区域在模型上以红色高亮显示

---

## M5：数据生命周期 + 飞轮闭环

- **状态**：待实施
- **优先级**：P2
- **模式**：Mode 2 (OpenSpec)
- **工作量**：8-12 天
- **依赖**：M1（持久化基础设施）

### 范围

| 子项 | 来源 | 涉及文件 | 说明 |
|------|------|---------|------|
| Benchmark _run_single() 实装 | data-analyst P2 | `backend/benchmark/runner.py:149-171` | 集成实际 V2 管道调用，替换全 False 占位 |
| CadQuery 代码持久化 | data-analyst P1 | `backend/db/models.py`, `backend/graph/nodes/generation.py` | JobModel 新增 generated_code 字段 |
| parent_job_id 版本链 | data-analyst P1 | `backend/db/models.py`, `backend/api/v1/jobs.py` | 支持 Fork → 改参数 → 重生成，保留版本关系 |
| DesignPackage 归档结构 | data-analyst P1 | `backend/db/file_storage.py` | outputs/{job_id}/ 下分 input/intermediate/output 子目录 |
| 纠偏数据清洗脚本 | data-analyst P1 | 新建 `scripts/data/` | 过滤无效记录、关联 job → 构建训练三元组 |
| 纠偏统计仪表盘 | data-analyst P2 | 新建 API + 前端页面 | 按 field_path/part_type 统计修正频率，时间趋势 |
| SFT 微调管道 | data-analyst P2 | `scripts/training/sft_formatter.py`, `sft_config.py` | 纠偏数据 → JSONL → Qwen2.5-Coder-7B + LoRA 微调 |

### 验收标准

- [ ] Benchmark 5 个 case 可实际运行并输出评测报告
- [ ] Job 结果中包含生成的 CadQuery Python 代码
- [ ] 从历史零件"改参数重生成"时保留 parent_job_id 关联
- [ ] outputs/ 目录结构包含 input/intermediate/output 分层
- [ ] 纠偏数据统计 API 可返回 Top-20 高频修正字段
- [ ] SFT 训练脚本可从纠偏数据生成 JSONL 格式训练集

---

## 远期任务（不在当前 5 轮实施范围内）

| 任务 | 来源 | 优先级 | 说明 |
|------|------|--------|------|
| 用户系统 + 多租户 | data-analyst P0 | P0（商业化前提） | JWT + user_id + 数据隔离，商业化启动时再做 |
| Monaco 代码编辑器 | ux-analyst P3 | P3 | 高级用户修改 CadQuery 代码 |
| 切片器 / G-Code 集成 | innovation P3 | P3 | CuraEngine CLI 集成 + G-Code 预览 |
| 逆向工程管道 (Photo-to-CAD) | innovation 创新机会 | P3 | 复用 VLM + DrawingAnalyzer |
| CAD Agent 对话式编辑 | innovation 创新机会 | P3 | LangGraph + ReAct 对话式修改参数 |
| 车间直连 API | 6/6 共识 P4 | P4 | OctoPrint / 工业 MES 对接 |
