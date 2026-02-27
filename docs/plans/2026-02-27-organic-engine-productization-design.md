# 有机引擎产品化设计

> **前置文档:** [organic-shape-pipeline-design.md](./2026-02-27-organic-shape-pipeline-design.md) (概念设计)
> **日期:** 2026-02-27
> **状态:** 已审批，待实现

---

## 1. 定位与范围

### 目标

在 cad3dify V3 中新增完全独立的「有机引擎」管道，支持自然语言/参考图片输入生成自由曲面 3D 模型，并通过工程后处理（缩放、布尔切削、网格修复）输出可 3D 打印的工业级文件。

### 用户场景

| 场景 | 精度要求 | 质量档位 |
|------|---------|---------|
| 快速原型 / 概念验证 | 低（±1mm） | draft |
| 外观件 / 展示模型 | 中（±0.5mm） | standard |
| 带工程接口的功能件（如高尔夫球头 + 插杆孔） | 高（接口精确） | high |

### 架构决策

**方案 A：完全独立管道** — 独立 API、独立前端页面、独立状态管理，不侵入现有机械管道代码。预留向共享基础设施演进的接口。

---

## 2. 技术选型

### 2.1 3D 生成 API（云 API 优先）

| Provider | 角色 | 中国可用 | 成本/次 | 延迟 | 特点 |
|----------|------|---------|--------|------|------|
| **Tripo3D** | 主通道 | 原生可用（北京 VAST） | ¥0.1-1.5 | 10-60s | Python SDK、开源 fallback |
| **Hunyuan3D** | 备通道 | 原生可用（腾讯云） | 免费额度/腾讯云计费 | 8-20s | Apache 2.0 开源、可自部署 |

**auto 策略：** Tripo3D 优先 → 失败/超时 → fallback Hunyuan3D。

### 2.2 网格后处理库

| 库 | 用途 | 可靠性 |
|----|------|--------|
| **manifold3d** ≥3.0 | 布尔运算（唯一保证 manifold 输出） | 生产级 |
| **PyMeshLab** ≥2025.0 | 网格修复（非流形边/顶点、法线、补洞） | 工业级 |
| **trimesh** ≥4.5.0（已有） | 网格 I/O、分析、缩放、格式转换 | 成熟 |

### 2.3 后处理管线

```
AI 生成网格 (GLB/OBJ)
  → PyMeshLab 修复（非流形、法线、补洞）
  → trimesh 缩放对齐（归一化到目标包围盒）
  → manifold3d 布尔运算（平底切削、安装孔）
  → trimesh 质量校验（watertight、体积、包围盒）
  → 导出 STL / 3MF / GLB
```

---

## 3. 数据流与状态机

### 3.1 端到端数据流

```
用户输入 (Prompt + 可选参考图 + 约束配置)
  │
  ├─ Stage 1: OrganicSpecBuilder (LLM)
  │   输入: prompt + reference_image
  │   输出: OrganicSpec {
  │     prompt_en,                    # 英文 prompt（API 需要）
  │     bounding_box,                 # 目标包围盒 [x, y, z] mm
  │     engineering_cuts: [           # 工程接口约束
  │       { type: "flat_bottom" },
  │       { type: "hole", diameter: 10, depth: 20, position: [0,0,-15] }
  │     ],
  │     quality_mode: "draft" | "standard" | "high"
  │   }
  │
  ├─ Stage 2: MeshGenerator
  │   输入: OrganicSpec.prompt_en + reference_image
  │   调用: Tripo3D API (主) / Hunyuan3D (备)
  │   输出: raw_mesh.glb
  │   耗时: 10-90 秒
  │
  ├─ Stage 3: MeshPostProcessor
  │   3a. PyMeshLab 修复
  │   3b. trimesh 缩放到 bounding_box
  │   3c. manifold3d 布尔切削
  │   3d. 质量校验
  │   输出: processed_mesh.stl
  │
  ├─ Stage 4: 格式导出
  │   → STL / 3MF / GLB
  │
  └─ Stage 5: 可选打印性检查 (复用现有 PrintabilityChecker)
```

### 3.2 SSE 状态机

```
created → analyzing → generating → post_processing → completed
                                                       ↗
         → failed (任何阶段失败时)
```

对比机械管道：
- 无 `awaiting_confirmation` 阶段（约束在输入时配好）
- 无 `refining` 阶段（AI 网格无法像代码一样迭代修复）
- 增加 `post_processing` 阶段（布尔切削 + 网格修复）

### 3.3 SSE 事件序列

```
每个 SSE 事件包含标准信封字段：`job_id`、`status`、`message`、`progress`（0-1 浮点数），阶段相关字段为可选扩展。

data: {"job_id": "xxx", "status": "created", "message": "任务已创建", "progress": 0}
data: {"job_id": "xxx", "status": "analyzing", "message": "正在分析创意需求…", "progress": 0.05}
data: {"job_id": "xxx", "status": "generating", "message": "AI 正在生成 3D 模型…", "progress": 0.3, "provider": "tripo3d"}
data: {"job_id": "xxx", "status": "generating", "message": "3D 模型生成完成", "progress": 0.6}
data: {"job_id": "xxx", "status": "post_processing", "message": "正在修复网格…", "progress": 0.65, "step": "repair"}
data: {"job_id": "xxx", "status": "post_processing", "message": "正在缩放到目标尺寸…", "progress": 0.75, "step": "scale"}
data: {"job_id": "xxx", "status": "post_processing", "message": "正在切削工程接口…", "progress": 0.85, "step": "boolean"}
data: {"job_id": "xxx", "status": "post_processing", "message": "正在校验网格质量…", "progress": 0.95, "step": "validate"}
data: {"job_id": "xxx", "status": "completed", "message": "生成完成", "progress": 1.0, "model_url": "/outputs/xxx/model.glb", "mesh_stats": {...}}
```

---

## 4. API 设计

### 4.1 端点

```
POST /api/generate/organic             # 文本输入 → SSE 流
POST /api/generate/organic/upload      # 图片上传（≤10MB, png/jpeg/webp）→ SSE 流
GET  /api/generate/organic/{job_id}    # Job 状态查询 + 断连恢复
GET  /api/generate/organic/providers   # 查询可用生成服务商及状态
```

### 4.2 请求体（文本模式）

```json
{
  "prompt": "高尔夫发球木球头，流线型，碳纤维质感",
  "reference_image": null,
  "constraints": {
    "bounding_box": [80, 80, 60],
    "engineering_cuts": [
      { "type": "flat_bottom" },
      { "type": "hole", "diameter": 10, "depth": 25, "position": [0, 0, 0], "direction": "bottom" }
    ]
  },
  "quality_mode": "standard",
  "provider": "auto"
}
```

### 4.3 请求体（图片模式）

```
multipart/form-data:
  image: File
  prompt: "高尔夫球头"         (可选文字补充)
  constraints: JSON string
  quality_mode: "standard"
  provider: "auto"
```

### 4.4 质量档位映射

| quality_mode | 生成 API 设定 | 后处理 | 典型耗时 |
|-------------|-------------|--------|---------|
| draft | 低精度/快速模式 | 仅修复 + 缩放 | 15-30s |
| standard | 标准精度 | 修复 + 缩放 + 布尔切削 | 30-90s |
| high | 高精度/Quad mesh | 全部后处理 + 二次平滑 | 60-180s |

---

## 5. 数据模型

```python
# backend/models/organic.py

class FlatBottomCut(BaseModel):
    """平底切削"""
    type: Literal["flat_bottom"] = "flat_bottom"
    offset: float = Field(default=0.0, ge=0.0, description="距底部偏移量 mm")

class HoleCut(BaseModel):
    """圆柱孔切削"""
    type: Literal["hole"] = "hole"
    diameter: float = Field(..., gt=0, le=200, description="孔径 mm")
    depth: float = Field(..., gt=0, le=500, description="孔深 mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"

class SlotCut(BaseModel):
    """槽切削"""
    type: Literal["slot"] = "slot"
    width: float = Field(..., gt=0, le=200, description="槽宽 mm")
    depth: float = Field(..., gt=0, le=500, description="槽深 mm")
    length: float = Field(..., gt=0, le=500, description="槽长 mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"

EngineeringCut = Annotated[
    FlatBottomCut | HoleCut | SlotCut,
    Field(discriminator="type")
]

class OrganicConstraints(BaseModel):
    """有机模型的工程约束"""
    bounding_box: tuple[float, float, float] | None = None  # [x, y, z] mm
    engineering_cuts: list[EngineeringCut] = Field(default_factory=list)

class OrganicGenerateRequest(BaseModel):
    """有机管道生成请求"""
    prompt: str = Field(..., min_length=1, max_length=2000)
    reference_image: str | None = None
    constraints: OrganicConstraints = Field(default_factory=OrganicConstraints)
    quality_mode: Literal["draft", "standard", "high"] = "standard"
    provider: Literal["auto", "tripo3d", "hunyuan3d"] = "auto"

class OrganicSpec(BaseModel):
    """LLM 解析后的有机模型规范"""
    prompt_en: str
    prompt_original: str
    shape_category: str
    suggested_bounding_box: tuple[float, float, float] | None
    final_bounding_box: tuple[float, float, float] | None
    engineering_cuts: list[EngineeringCut]
    negative_prompt: str = ""

class MeshStats(BaseModel):
    """网格质量统计"""
    vertex_count: int
    face_count: int
    is_watertight: bool
    volume_cm3: float | None
    bounding_box: dict[str, float]
    has_non_manifold: bool
    repairs_applied: list[str]
    boolean_cuts_applied: int

class OrganicJobResult(BaseModel):
    """有机管道生成结果"""
    model_url: str
    stl_url: str | None
    threemf_url: str | None
    mesh_stats: MeshStats
    provider_used: str
    generation_time_s: float
    post_processing_time_s: float
```

### Provider 抽象层

```python
# backend/infra/mesh_providers/base.py

class MeshProvider(ABC):
    @abstractmethod
    async def generate(self, spec: OrganicSpec, image: bytes | None,
                       on_progress: Callable) -> Path: ...

    @abstractmethod
    async def check_health(self) -> bool: ...

# tripo.py — Tripo3D API: 创建任务 → 轮询状态(2s) → 下载 GLB
# hunyuan.py — Hunyuan3D API: 腾讯云调用 → 下载结果
```

### MeshPostProcessor

```python
# backend/core/mesh_post_processor.py

class MeshPostProcessor:
    async def process(self, raw_mesh_path: Path, spec: OrganicSpec,
                      on_progress: Callable) -> ProcessedMeshResult:
        # Step 1: PyMeshLab 修复 — 非流形边/顶点、法线、补洞
        # Step 2: trimesh 缩放 — 归一化到 final_bounding_box
        # Step 3: manifold3d 布尔 — flat_bottom / hole / slot
        # Step 4: 质量校验 — watertight + 体积 + 包围盒
        ...
```

---

## 6. 前端设计

### 6.1 导航重构

**菜单结构（二级）：**

```
🏠 首页                          /
🔧 精密建模
   ├─ ⚙️ 文本/图纸生成            /generate
   ├─ 📐 参数化模板               /templates
   ├─ 📖 工程标准                 /standards
   └─ 📊 评测基准                 /benchmark
🎨 创意雕塑                      /generate/organic
⚙️ 设置                          /settings
```

**首页改版：**
- 第一层：两张大卡片 — 精密建模 / 创意雕塑（核心分流入口）
- 第二层：三张小卡片 — 模板 / 标准 / 评测（辅助功能）
- Header 更新为「AI 驱动的 3D 模型生成平台」

### 6.2 有机生成页面布局

```
┌──────────────────────────────────────────────────────┐
│  创意雕塑生成                            [重新开始]   │
│  输入创意描述或上传参考图，AI 生成自由曲面 3D 模型     │
├─────────────────────┬────────────────────────────────┤
│  左侧面板           │  右侧 3D Viewer                │
│                     │                                │
│  ┌ 创意输入 ──────┐ │  ┌──────────────────────────┐  │
│  │ [文本] [图片]  │ │  │  Three.js 3D 预览        │  │
│  │ 文本区 / 上传  │ │  │  (复用 Viewer3D 组件)     │  │
│  │         [生成] │ │  └──────────────────────────┘  │
│  └───────────────┘ │                                │
│                     │                                │
│  ┌ 工程约束 ──────┐ │                                │
│  │ 包围盒 X Y Z   │ │                                │
│  │ ☑ 平底切削     │ │                                │
│  │ + 添加安装孔    │ │                                │
│  └───────────────┘ │                                │
│                     │                                │
│  ┌ 生成配置 ──────┐ │                                │
│  │ 质量: 草稿/标准 │ │                                │
│  │       /高质量   │ │                                │
│  │ 服务: 自动      │ │                                │
│  └───────────────┘ │                                │
│                     │                                │
│  ┌ 进度 ─────────┐ │                                │
│  │ ████████░░ 80% │ │                                │
│  └───────────────┘ │                                │
│                     │                                │
│  ┌ 下载 + 统计 ──┐ │                                │
│  │ [STL] [3MF]   │ │                                │
│  │ 顶点/面数/体积 │ │                                │
│  └───────────────┘ │                                │
└─────────────────────┴────────────────────────────────┘
```

### 6.3 组件复用与新增

| 组件 | 来源 | 说明 |
|------|------|------|
| `Viewer3D` | 复用 | GLB 加载渲染 |
| `OrganicInput` | 新增 | Tab 切换文本/图片输入 |
| `ConstraintForm` | 新增 | 包围盒 + 工程接口动态增删 |
| `QualitySelector` | 新增 | 三档质量 + Provider Radio |
| `OrganicWorkflow` | 新增 | 进度条（4 步） |
| `MeshStatsCard` | 新增 | 网格统计卡片 |
| `OrganicDownloadButtons` | 新增 | STL/3MF 下载 |

### 6.4 状态管理

```typescript
// OrganicWorkflowContext.tsx
interface OrganicWorkflowState {
  phase: 'idle' | 'analyzing' | 'generating' | 'post_processing' | 'completed' | 'failed';
  jobId: string | null;
  message: string;
  progress: number;
  error: string | null;
  modelUrl: string | null;
  meshStats: MeshStats | null;
  providerUsed: string | null;
}
```

App.tsx 中 `<OrganicWorkflowProvider>` 与 `<GenerateWorkflowProvider>` 并列包裹路由。

---

## 7. 文件清单

### 新增文件（14 个）

**后端（7 个）：**
- `backend/api/organic.py`
- `backend/core/organic_spec_builder.py`
- `backend/core/mesh_post_processor.py`
- `backend/models/organic.py`
- `backend/infra/mesh_providers/__init__.py`
- `backend/infra/mesh_providers/base.py`
- `backend/infra/mesh_providers/tripo.py`
- `backend/infra/mesh_providers/hunyuan.py`

**前端（7 个）：**
- `frontend/src/pages/OrganicGenerate/index.tsx`
- `frontend/src/pages/OrganicGenerate/OrganicInput.tsx`
- `frontend/src/pages/OrganicGenerate/ConstraintForm.tsx`
- `frontend/src/pages/OrganicGenerate/QualitySelector.tsx`
- `frontend/src/pages/OrganicGenerate/OrganicWorkflow.tsx`
- `frontend/src/pages/OrganicGenerate/MeshStatsCard.tsx`
- `frontend/src/pages/OrganicGenerate/OrganicDownloadButtons.tsx`
- `frontend/src/contexts/OrganicWorkflowContext.tsx`
- `frontend/src/types/organic.ts`

### 修改文件（6 个）

| 文件 | 改动 |
|------|------|
| `backend/main.py` | 挂载 organic_router |
| `frontend/src/App.tsx` | 新增路由 + OrganicWorkflowProvider |
| `frontend/src/layouts/MainLayout.tsx` | 二级菜单结构 |
| `frontend/src/pages/Home/index.tsx` | 双入口卡片布局 |
| `pyproject.toml` | 新增 manifold3d, pymeshlab |
| `.env.sample` | 新增 TRIPO3D_API_KEY, HUNYUAN3D_API_KEY |

### 不动的核心代码

- `backend/api/generate.py` — 机械管道不动
- `backend/core/` 下现有所有模块 — 不动
- `backend/pipeline/` — 不动
- `frontend/src/pages/Generate/` — 不动
- `frontend/src/components/Viewer3D/` — 复用不改

---

## 8. 可行性评估

### 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| AI 网格不 watertight | 中 | PyMeshLab 修复 + manifold3d 保证布尔输出 manifold |
| Tripo3D API 不稳定 | 低 | Hunyuan3D fallback + 超时重试 |
| manifold3d 布尔运算对低质量网格失败 | 中 | PyMeshLab 先修复再布尔；失败时跳过布尔返回仅修复版本 |
| 国内网络访问 API | 低 | Tripo3D 和 Hunyuan3D 均为国内公司/云服务 |
| 生成结果不符合预期 | 中 | 先展示 raw mesh 3D 预览，用户确认后再做后处理 |
| PyMeshLab GPL v3 许可传染性 | 中 | 可选依赖 + 进程隔离；闭源时切换 manifold3d 自带修复 |
| organic 依赖导入崩溃影响全局 | 中 | feature-gate（ORGANIC_ENABLED）+ 懒加载重型依赖 |
| 客户端断连孤立付费任务 | 中 | Job 状态持久化 + GET /{job_id} 恢复端点 |
| 布尔切削精度期望不现实 | 低 | 公差模型：standard ±0.2mm，high ±0.1mm |

### 依赖评估

| 依赖 | 成熟度 | 许可证 |
|------|--------|--------|
| manifold3d 3.x | 生产级（Google 支持） | Apache 2.0 |
| pymeshlab 2025.x | 工业级（CNR-ISTI 维护） | GPL v3 |
| trimesh 4.x | 成熟（已在项目中） | MIT |
| Tripo Python SDK | 官方维护 | MIT |

> **许可证策略：** PyMeshLab 为 GPL v3 许可。MVP 阶段作为可选依赖使用（进程隔离）。闭源发布时可切换到 manifold3d 自带修复能力 + trimesh 基础修复（均为非 GPL）。详见 OpenSpec design.md D6。
