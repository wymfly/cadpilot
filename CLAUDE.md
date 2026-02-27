# CAD3Dify

> AI 驱动的 2D 工程图纸 → 3D CAD 模型生成工具，目标演进为自然语言到工业级 3D 打印文件平台。

## 语言

- 使用中文回答

---

## 当前状态

**V2（生产）**：2D 工程图纸 → CadQuery 代码 → STEP 文件，Streamlit 前端
**V3（规划）**：自然语言 + 参数表 → 工业级 3D 打印文件，前后端分离架构

V3 设计文档：`openspec/changes/2026-02-26-v3-text-to-printable/`

---

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.10+ |
| CAD 内核 | CadQuery 2.4.0（基于 OCCT） |
| LLM 框架 | LangChain 0.3.18+ |
| LLM 后端 | Qwen-VL-Max（读图）、Qwen-Coder-Plus（代码）、GPT-5、Claude、Gemini |
| 数据验证 | Pydantic v2 |
| Web UI | Streamlit 1.37.1（V2）→ React + Three.js（V3） |
| 后端 | 无（V2 单体）→ FastAPI :8780（V3） |
| 包管理 | uv（pyproject.toml + uv.lock） |

---

## 架构

### V2 管道（当前）

```
图纸(PNG/JPG)
  → Stage 1: DrawingAnalyzerChain (qwen-vl-max, temp=0.1) → DrawingSpec
  → Stage 1.5: ModelingStrategist (规则引擎) → 策略 + few-shot 示例
  → Stage 2: CodeGeneratorChain (qwen-coder-plus, temp=0.3) → CadQuery 代码
  → Stage 3: execute_python_code (ReAct) → STEP 文件
  → Stage 3.5: validate_step_geometry → 几何验证
  → Stage 4: SmartRefiner (最多 3 轮, 零风险模式)
      ├─ Layer 1: 静态参数校验（仅诊断）
      ├─ Layer 2: 包围盒校验（仅诊断）
      └─ Layer 3: VL 对比（唯一裁判）→ Coder 修复
```

### V3 目标架构（见 openspec）

```
用户输入 (自然语言/参数表/图片)
  → Phase 1: IntentParser → IntentSpec
  → Phase 2: 参数补全 + 用户确认 → PreciseSpec
  → Phase 3: ParametricTemplate / LLM fallback → STEP
  → Phase 4: PrintabilityChecker → 可打印性报告
  → Phase 5: STEP + STL/3MF + 参数化源码
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
cad3dify/                    # 核心库
├── __init__.py              # 公共 API：generate_step_v2, generate_step_from_2d_cad_image
├── pipeline.py              # V1/V2 管道主函数
├── agents.py                # ReAct 代码执行代理
├── chat_models.py           # MODEL_TYPE + ChatModelParameters
├── image.py                 # ImageData（Base64 图像处理）
├── render.py                # STEP → SVG → PNG 渲染
├── v1/                      # 经典管道（fallback）
│   ├── cad_code_generator.py
│   └── cad_code_refiner.py
├── v2/                      # 增强管道（当前重点）
│   ├── drawing_analyzer.py  # VL 图纸分析 → DrawingSpec
│   ├── modeling_strategist.py  # 策略选择 + 示例检索
│   ├── code_generator.py    # CadQuery 代码生成
│   ├── smart_refiner.py     # 三层防线智能改进
│   └── validators.py        # 参数 + 几何校验
└── knowledge/               # 知识库
    ├── part_types.py        # DrawingSpec, PartType, BaseBodySpec
    ├── modeling_strategies.py  # 7 种零件建模策略
    └── examples/            # 20 个 few-shot 代码示例
        ├── _base.py         # TaggedExample
        └── {rotational,plate,bracket,...}.py

scripts/                     # 应用入口
├── app.py                   # Streamlit Web UI (:8501)
└── cli.py                   # CLI 工具

tests/                       # pytest 单元测试
├── conftest.py              # MetaPathFinder stub（重型包 mock）
├── test_drawing_analyzer.py
├── test_knowledge_base.py
├── test_modeling_strategist.py
├── test_smart_refiner.py
└── test_validators.py

docs/                        # 文档
├── V2-CURRENT-CAPABILITIES.md
└── plans/                   # 设计文档 + 优化方案

openspec/                    # OpenSpec 设计规范
└── changes/2026-02-26-v3-text-to-printable/
    ├── proposal.md          # 需求提案
    ├── design.md            # 技术设计（6 ADR）
    └── tasks.md             # 44 个任务（6 Phase）

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
# V3 前后端（推荐）
./scripts/start-v3.sh          # 启动后端 + 前端
./scripts/start-v3.sh backend  # 仅后端 (:8780)
./scripts/start-v3.sh frontend # 仅前端 (:3001)
./scripts/start-v3.sh stop     # 停止所有

# V2 Streamlit（旧版）
./start.sh qwen

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

### V1 → V2 降级
- Stage 1 解析失败时自动降级到 V1 管道（`generate_step_from_2d_cad_image`）
- 保持 V1 代码可用

### 测试 Stub 机制
- `conftest.py` 的 `MetaPathFinder` 拦截 langchain/cadquery/matplotlib 等重型包
- 测试中不需要实际安装 CadQuery 或 GPU 依赖
- 新增测试如需真实包导入，在 `conftest.py` 的排除列表中添加

---

## 参考文档

- `docs/V2-CURRENT-CAPABILITIES.md` — V2 完整能力说明
- `docs/plans/2026-02-26-v2-quality-improvement-directions.md` — 质量优化方向（13 方案）
- `docs/plans/2026-02-26-v3-tech-research.md` — V3 技术调研（8 个对标项目）
- `openspec/changes/2026-02-26-v3-text-to-printable/proposal.md` — V3 需求提案
- `openspec/changes/2026-02-26-v3-text-to-printable/design.md` — V3 技术设计（6 ADR + 模块设计）
- `openspec/changes/2026-02-26-v3-text-to-printable/tasks.md` — V3 任务分解（44 任务，6 Phase）
