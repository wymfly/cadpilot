# CADPilot

> AI 驱动的自然语言/工程图纸 → 工业级 3D CAD 模型生成平台。

## 语言

- 使用中文回答

---

## 当前状态

LangGraph 双管道架构：
- **精密管道（precision）**：2D 工程图纸 → CadQuery 代码 → STEP 文件
- **有机管道（organic）**：自然语言描述 → 3D 生成模型 → 网格修复 → 3D 打印文件

前后端分离：FastAPI 后端 + React + Three.js 前端

---

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.10+ |
| CAD 内核 | CadQuery 2.4.0（基于 OCCT） |
| LLM 框架 | LangChain 0.3.18+ |
| LLM 后端 | Qwen-VL-Max（读图）、Qwen-Coder-Plus（代码）、GPT-5、Claude、Gemini |
| 数据验证 | Pydantic v2 |
| Web UI | React + Three.js |
| 后端 | FastAPI :8780 |
| 包管理 | uv（pyproject.toml + uv.lock） |

---

## 架构

### LangGraph 双管道

```
用户输入 (自然语言/参数表/图片)
  → routing_node: 意图解析 + 管道路由
  ├─ precision 管道（工程图纸）:
  │    → analysis_node: DrawingAnalyzerChain → DrawingSpec
  │    → HITL interrupt: 用户确认/修正
  │    → generate_node: 策略选择 + CadQuery 代码生成 + 执行 + SmartRefiner
  │    → printability_node: 可打印性检查
  └─ organic 管道（自然语言描述）:
       → analysis_node: IntentParser → OrganicSpec
       → HITL interrupt: 用户确认参数
       → generate_raw_mesh_node: 3D 生成模型（Hunyuan3D/Tripo3D/SPAR3D/TRELLIS）
       → mesh_repair_node: 网格修复 + 流形化
       → mesh_scale_node: 尺寸缩放 + 对齐
       → printability_node: 可打印性检查
```

### 零件类型（7 种）

| PartType | 中文 | 成熟度 |
|----------|------|--------|
| ROTATIONAL | 回转体 | ★★★★ |
| ROTATIONAL_STEPPED | 阶梯回转体 | ★★★★ |
| PLATE | 板件 | ★★★☆ |
| BRACKET | 支架 | ★★★☆ |
| HOUSING | 壳体 | ★★☆☆ |
| GEAR | 齿轮 | ★★☆☆ |
| GENERAL | 通用 | ★★☆☆ |

---

## 项目结构

```
backend/                     # 后端（FastAPI + LangGraph）
├── main.py                  # FastAPI 入口
├── config.py                # 全局配置
├── api/v1/                  # REST API 路由
├── core/                    # 核心业务逻辑
│   ├── drawing_analyzer.py  # VL 图纸分析 → DrawingSpec
│   ├── modeling_strategist.py  # 策略选择 + 示例检索
│   ├── code_generator.py    # CadQuery 代码生成
│   ├── smart_refiner.py     # 三层防线智能改进
│   └── validators.py        # 参数 + 几何校验
├── graph/                   # LangGraph 管道编排
│   ├── builder.py           # 图构建器
│   ├── nodes/               # 管道节点（analysis, generate, mesh_repair 等）
│   ├── strategies/          # 节点策略（Hunyuan3D, Tripo3D 等）
│   ├── registry.py          # 节点注册表
│   └── context.py           # NodeContext
├── infra/                   # 基础设施（agents, image, render）
├── knowledge/               # 知识库
│   ├── part_types.py        # DrawingSpec, PartType, BaseBodySpec
│   ├── modeling_strategies.py  # 7 种零件建模策略
│   └── examples/            # few-shot 代码示例
├── models/                  # 数据模型
├── db/                      # 数据库（SQLAlchemy + aiosqlite）
└── pipeline/                # 管道辅助（sse_bridge 等）

frontend/                    # 前端（React + Three.js）

scripts/                     # 脚本
├── start.sh                 # 启动后端 + 前端
└── cli.py                   # CLI 工具

tests/                       # pytest 单元测试

docs/                        # 文档
└── plans/                   # 设计文档 + 优化方案

openspec/                    # OpenSpec 设计规范

sample_data/                 # 示例工程图纸
```

---

## 关键数据模型

```python
# 核心输入/输出
DrawingSpec          # VL 读图结果：零件类型 + 尺寸 + 特征
├── part_type: PartType
├── overall_dimensions: dict[str, float]
├── base_body: BaseBodySpec  # 基体（revolve/extrude/loft/sweep/shell）
├── features: list[dict]     # 孔阵、圆角、倒角等
└── notes: list[str]

ModelingContext       # 策略选择结果
├── drawing_spec: DrawingSpec
├── strategy: str            # 建模策略文本
└── examples: list[tuple]    # top-3 few-shot 示例

TaggedExample        # 知识库示例
├── name: str
├── description: str
├── tags: set[str]           # 语义特征标签
└── code: str                # CadQuery 代码

# 校验结果
ValidationResult     # 参数校验（mismatches + warnings）
GeometryResult       # 几何校验（is_valid + volume + bbox）
```

---

## 代码规范

- Python 3.10+，类型注解必须
- Black 88 字符行宽，isort 排序
- Pydantic v2 BaseModel 用于数据验证
- LangChain 链式组合模式
- 测试：pytest，conftest.py 中 MetaPathFinder 自动 stub 重型依赖

---

## 包管理与虚拟环境

**本项目使用 uv 管理虚拟环境和依赖，禁止使用系统 Python 或 conda。**

```bash
# 安装依赖
uv sync

# 添加依赖
uv add <package>

# 添加开发依赖
uv add --dev <package>

# 运行命令（自动使用 .venv）
uv run <command>
uv run pytest tests/ -v
uv run uvicorn backend.main:app --port 8780
```

**强制规则：**
- 所有 Python 命令必须通过 `uv run` 执行，或在 `.venv` 激活后执行
- 禁止使用 `python`/`pip`（系统级），必须 `uv run python`/`uv pip`
- `.venv` 由 uv 管理（Python 3.12），不要手动创建或修改

---

## 启动服务

```bash
# 前后端
./scripts/start.sh          # 启动后端 + 前端
./scripts/start.sh backend  # 仅后端 (:8780)
./scripts/start.sh frontend # 仅前端 (:3001)
./scripts/start.sh stop     # 停止所有

# CLI 生成
uv run python scripts/cli.py sample_data/g1-3.jpg --output_filepath output.step
```

---

## 验证命令

```bash
# 测试（必须通过 uv run）
uv run pytest tests/ -v

# 格式化
uv run black .
uv run isort .

# TypeScript
cd frontend && npx tsc --noEmit && npm run lint
```

---

## 环境配置

```bash
cp .env.sample .env
# 必需：OPENAI_API_KEY（用于 DashScope Qwen 兼容 API）
# 可选：ANTHROPIC_API_KEY, GOOGLE_API_KEY, VERTEXAI_*
```

DashScope 端点通过 `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1` 配置。

---

## 开发注意事项

### SmartRefiner 零风险设计
- Layer 1/2（静态校验/包围盒）仅提供诊断信息，**不**做最终判定
- Layer 3（VL 对比）是唯一裁判，始终运行
- 修改校验逻辑时保持此层级关系

### 知识库扩展
- 新增零件类型：`knowledge/examples/` 下添加模块 + 更新 `__init__.py` 的 `EXAMPLES_BY_TYPE`
- 新增建模策略：`knowledge/modeling_strategies.py` 中添加对应 PartType
- Jaccard 相似度用于示例匹配，标签设计影响匹配质量

### 测试 Stub 机制
- `conftest.py` 的 `MetaPathFinder` 拦截 langchain/cadquery/matplotlib 等重型包
- 测试中不需要实际安装 CadQuery 或 GPU 依赖
- 新增测试如需真实包导入，在 `conftest.py` 的排除列表中添加

---

## 参考文档

- `docs/plans/2026-02-26-v2-quality-improvement-directions.md` — 质量优化方向（13 方案）
- `docs/plans/2026-02-26-v3-tech-research.md` — 技术调研（8 个对标项目）
- `openspec/changes/2026-02-26-v3-text-to-printable/proposal.md` — 需求提案
- `openspec/changes/2026-02-26-v3-text-to-printable/design.md` — 技术设计（6 ADR + 模块设计）
- `openspec/changes/2026-02-26-v3-text-to-printable/tasks.md` — 任务分解（44 任务，6 Phase）
