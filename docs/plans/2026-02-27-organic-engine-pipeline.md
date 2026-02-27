# Organic Engine Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fully independent organic engine pipeline (Text/Image-to-3D via cloud AI APIs + mesh post-processing) alongside the existing mechanical pipeline.

**Architecture:** Completely independent pipeline — separate API router, models, frontend page, and state management. The organic router is always mounted but feature-gated (`ORGANIC_ENABLED`), with heavy dependencies lazy-loaded in handlers.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, manifold3d, PyMeshLab, trimesh, Tripo3D SDK, React 18, Ant Design 6, TypeScript 5.6

**OpenSpec:** `openspec/changes/organic-engine-pipeline/`

**Design Doc:** `docs/plans/2026-02-27-organic-engine-productization-design.md`

---

## Dependency Graph

```
Phase A (Foundation):      Task 1 → Task 2
Phase B (Parallel Core):   Task 3 ┐
                           Task 4 ├─ (parallel, all depend on Task 2)
                           Task 5 ┘
Phase C (API Integration): Task 6 (depends on 2, 3, 4, 5)
Phase D (Frontend):        Task 7 → Task 8 (parallel with Phase B/C)
Phase E (E2E):             Task 9 (depends on 6, 8)
```

---

### Task 1: Dependencies & Configuration `[backend]`

**Files:**
- Modify: `pyproject.toml:9-35`
- Modify: `backend/config.py`
- Modify: `.env.sample`

**Step 1: Add Python dependencies**

In `pyproject.toml`, add to `dependencies` list:

```python
    "manifold3d>=3.0.0",
    "trimesh>=4.5.0",        # already present
```

Add to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
vertexai = ["langchain-google-vertexai>=2.0.1,<3.0"]
mesh-repair = ["pymeshlab>=2025.0"]
```

**Step 2: Add configuration fields**

In `backend/config.py`, add to `Settings`:

```python
    # Organic engine
    organic_enabled: bool = True
    tripo3d_api_key: str | None = None
    hunyuan3d_api_key: str | None = None
    organic_default_provider: str = "auto"  # "auto" | "tripo3d" | "hunyuan3d"
    organic_upload_max_mb: int = 10
```

In `.env.sample`, add:

```bash
# Organic Engine
ORGANIC_ENABLED=true
TRIPO3D_API_KEY=
HUNYUAN3D_API_KEY=
ORGANIC_DEFAULT_PROVIDER=auto
```

**Step 3: Verify installation**

Run: `uv sync`
Run: `uv run python -c "import manifold3d; print(manifold3d.__version__)"`
Expected: Version ≥3.0.0

**Step 4: Add stub roots for tests**

In `tests/conftest.py`, add `"manifold3d"`, `"pymeshlab"` to `_STUB_ROOTS` so unit tests don't need these heavy packages.

**Step 5: Commit**

```bash
git add pyproject.toml backend/config.py .env.sample tests/conftest.py
git commit -m "feat(organic): add manifold3d, pymeshlab dependencies and config"
```

---

### Task 2: Backend Data Models `[backend]` `[test]`

**Files:**
- Create: `backend/models/organic.py`
- Create: `tests/test_organic_models.py`

**Step 1: Write the failing test**

Create `tests/test_organic_models.py`:

```python
"""Tests for organic pipeline Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_flat_bottom_cut_defaults():
    from backend.models.organic import FlatBottomCut
    cut = FlatBottomCut()
    assert cut.type == "flat_bottom"
    assert cut.offset == 0.0


def test_hole_cut_requires_diameter_and_depth():
    from backend.models.organic import HoleCut
    with pytest.raises(ValidationError):
        HoleCut()  # missing required fields
    hole = HoleCut(diameter=10.0, depth=25.0)
    assert hole.direction == "bottom"


def test_slot_cut_requires_dimensions():
    from backend.models.organic import SlotCut
    with pytest.raises(ValidationError):
        SlotCut()  # missing required fields
    slot = SlotCut(width=5.0, depth=10.0, length=20.0)
    assert slot.type == "slot"


def test_hole_cut_rejects_invalid_values():
    from backend.models.organic import HoleCut
    with pytest.raises(ValidationError):
        HoleCut(diameter=-1, depth=10)
    with pytest.raises(ValidationError):
        HoleCut(diameter=10, depth=0)


def test_discriminated_union_dispatch():
    from backend.models.organic import OrganicConstraints
    constraints = OrganicConstraints(
        bounding_box=(80, 80, 60),
        engineering_cuts=[
            {"type": "flat_bottom"},
            {"type": "hole", "diameter": 10, "depth": 25},
        ],
    )
    assert len(constraints.engineering_cuts) == 2
    assert constraints.engineering_cuts[0].type == "flat_bottom"
    assert constraints.engineering_cuts[1].type == "hole"


def test_organic_constraints_default_factory():
    from backend.models.organic import OrganicConstraints
    c1 = OrganicConstraints()
    c2 = OrganicConstraints()
    assert c1.engineering_cuts is not c2.engineering_cuts  # no shared mutable default


def test_organic_generate_request_validation():
    from backend.models.organic import OrganicGenerateRequest
    req = OrganicGenerateRequest(prompt="高尔夫球头")
    assert req.quality_mode == "standard"
    assert req.provider == "auto"


def test_organic_generate_request_rejects_empty_prompt():
    from backend.models.organic import OrganicGenerateRequest
    with pytest.raises(ValidationError):
        OrganicGenerateRequest(prompt="")


def test_mesh_stats_serialization():
    from backend.models.organic import MeshStats
    stats = MeshStats(
        vertex_count=1000,
        face_count=2000,
        is_watertight=True,
        volume_cm3=12.5,
        bounding_box={"x": 80, "y": 80, "z": 60},
        has_non_manifold=False,
        repairs_applied=["fix_normals"],
        boolean_cuts_applied=2,
    )
    d = stats.model_dump()
    assert d["is_watertight"] is True
    assert d["boolean_cuts_applied"] == 2


def test_organic_job_result():
    from backend.models.organic import MeshStats, OrganicJobResult
    stats = MeshStats(
        vertex_count=100, face_count=200, is_watertight=True,
        volume_cm3=1.0, bounding_box={"x": 10, "y": 10, "z": 10},
        has_non_manifold=False, repairs_applied=[], boolean_cuts_applied=0,
    )
    result = OrganicJobResult(
        job_id="test-123",
        model_url="/outputs/test/model.glb",
        mesh_stats=stats,
        provider_used="tripo3d",
        generation_time_s=15.0,
        post_processing_time_s=5.0,
    )
    assert result.stl_url is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_organic_models.py -v`
Expected: FAIL (ImportError — module not yet created)

**Step 3: Write the implementation**

Create `backend/models/organic.py`:

```python
"""Pydantic models for the organic generation pipeline.

EngineeringCut uses discriminated union — each cut type has its own
model with type-specific required fields and value constraints.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Engineering cut types (discriminated union on "type")
# ---------------------------------------------------------------------------

class FlatBottomCut(BaseModel):
    """Flat bottom cut for stable 3D printing placement."""
    type: Literal["flat_bottom"] = "flat_bottom"
    offset: float = Field(default=0.0, ge=0.0, description="Offset from bottom in mm")


class HoleCut(BaseModel):
    """Cylindrical hole cut."""
    type: Literal["hole"] = "hole"
    diameter: float = Field(..., gt=0, le=200, description="Hole diameter in mm")
    depth: float = Field(..., gt=0, le=500, description="Hole depth in mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"


class SlotCut(BaseModel):
    """Rectangular slot cut."""
    type: Literal["slot"] = "slot"
    width: float = Field(..., gt=0, le=200, description="Slot width in mm")
    depth: float = Field(..., gt=0, le=500, description="Slot depth in mm")
    length: float = Field(..., gt=0, le=500, description="Slot length in mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"


EngineeringCut = Annotated[
    FlatBottomCut | HoleCut | SlotCut,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Constraints & request
# ---------------------------------------------------------------------------

class OrganicConstraints(BaseModel):
    """Engineering constraints for organic model post-processing."""
    bounding_box: tuple[float, float, float] | None = None
    engineering_cuts: list[EngineeringCut] = Field(default_factory=list)


class OrganicGenerateRequest(BaseModel):
    """Request body for organic generation endpoint."""
    prompt: str = Field(..., min_length=1, max_length=2000)
    reference_image: str | None = None
    constraints: OrganicConstraints = Field(default_factory=OrganicConstraints)
    quality_mode: Literal["draft", "standard", "high"] = "standard"
    provider: Literal["auto", "tripo3d", "hunyuan3d"] = "auto"


# ---------------------------------------------------------------------------
# OrganicSpec (LLM-constructed)
# ---------------------------------------------------------------------------

class OrganicSpec(BaseModel):
    """Spec built by OrganicSpecBuilder from user input + LLM."""
    prompt_en: str
    prompt_original: str
    shape_category: str
    suggested_bounding_box: tuple[float, float, float] | None = None
    final_bounding_box: tuple[float, float, float] | None = None
    engineering_cuts: list[EngineeringCut] = Field(default_factory=list)
    quality_mode: Literal["draft", "standard", "high"] = "standard"
    negative_prompt: str = ""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class MeshStats(BaseModel):
    """Mesh quality statistics after post-processing."""
    vertex_count: int
    face_count: int
    is_watertight: bool
    volume_cm3: float | None = None
    bounding_box: dict[str, float]
    has_non_manifold: bool
    repairs_applied: list[str] = Field(default_factory=list)
    boolean_cuts_applied: int = 0


class OrganicJobResult(BaseModel):
    """Result payload for a completed organic generation job."""
    job_id: str
    model_url: str
    stl_url: str | None = None
    threemf_url: str | None = None
    mesh_stats: MeshStats
    provider_used: str
    generation_time_s: float
    post_processing_time_s: float
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_organic_models.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add backend/models/organic.py tests/test_organic_models.py
git commit -m "feat(organic): add Pydantic models with discriminated union EngineeringCut"
```

---

### Task 3: Provider Abstraction Layer `[backend]` `[test]`

**Files:**
- Create: `backend/infra/mesh_providers/__init__.py`
- Create: `backend/infra/mesh_providers/base.py`
- Create: `backend/infra/mesh_providers/tripo.py`
- Create: `backend/infra/mesh_providers/hunyuan.py`
- Create: `backend/infra/mesh_providers/auto.py`
- Create: `tests/test_mesh_providers.py`

**Step 1: Write the failing test**

Create `tests/test_mesh_providers.py` with tests for:
- `MeshProvider` ABC cannot be instantiated
- `TripoProvider.generate()` with mocked httpx responses (create task → poll → download)
- `TripoProvider` timeout and retry behavior
- `HunyuanProvider.generate()` with mocked responses
- `AutoProvider` fallback: Tripo fails → Hunyuan succeeds
- `AutoProvider` all fail → raises
- `check_health()` returns bool

**Step 2: Run test to verify fails**

Run: `uv run pytest tests/test_mesh_providers.py -v`
Expected: FAIL (ImportError)

**Step 3: Implement MeshProvider base**

Create `backend/infra/mesh_providers/base.py`:
- `MeshProvider(ABC)` with `generate(spec, image, on_progress) -> Path` and `check_health() -> bool`

**Step 4: Implement TripoProvider**

Create `backend/infra/mesh_providers/tripo.py`:
- `TripoProvider(MeshProvider)` using httpx async client
- `generate()`: POST create task → poll status every 2s → download GLB
- Timeout: 120s for standard, 300s for high
- Retry: 1 retry on transient errors

**Step 5: Implement HunyuanProvider**

Create `backend/infra/mesh_providers/hunyuan.py`:
- `HunyuanProvider(MeshProvider)` using httpx async client
- Tencent Cloud API integration

**Step 6: Implement AutoProvider**

Create `backend/infra/mesh_providers/auto.py`:
- `AutoProvider(MeshProvider)` wrapping Tripo + Hunyuan
- `generate()`: try Tripo → on failure/timeout → try Hunyuan
- `check_health()`: returns True if either provider is healthy

**Step 7: Run tests**

Run: `uv run pytest tests/test_mesh_providers.py -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add backend/infra/mesh_providers/ tests/test_mesh_providers.py
git commit -m "feat(organic): add MeshProvider abstraction with Tripo3D, Hunyuan3D, auto fallback"
```

---

### Task 4: Mesh Post-Processing Pipeline `[backend]` `[test]`

**Files:**
- Create: `backend/core/mesh_post_processor.py`
- Create: `tests/test_mesh_post_processor.py`

**Step 1: Write failing tests**

Create `tests/test_mesh_post_processor.py`:
- Test `process()` with a simple cube mesh (trimesh primitive)
- Test repair step fixes non-manifold edges (mock PyMeshLab)
- Test scale step fits mesh into target bounding box
- Test boolean flat_bottom cut creates planar bottom
- Test boolean hole cut creates cylindrical void
- Test quality validation reports correct stats
- Test graceful degradation: boolean fails → returns repaired+scaled mesh with warning
- Test draft mode skips boolean step

**Step 2: Run tests — verify fail**

Run: `uv run pytest tests/test_mesh_post_processor.py -v`

**Step 3: Implement MeshPostProcessor skeleton**

Create `backend/core/mesh_post_processor.py`:
```python
class MeshPostProcessor:
    async def process(
        self,
        raw_mesh_path: Path,
        spec: OrganicSpec,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> ProcessedMeshResult:
        mesh = self._load_mesh(raw_mesh_path)
        mesh = await self._repair(mesh, on_progress)
        mesh = self._scale(mesh, spec.final_bounding_box, on_progress)
        if spec.quality_mode != "draft":
            mesh = self._boolean_cuts(mesh, spec.engineering_cuts, on_progress)
        stats = self._validate(mesh, on_progress)
        return ProcessedMeshResult(mesh=mesh, stats=stats)
```

**Step 4: Implement repair step** — PyMeshLab lazy import, fix non-manifold, unify normals, close holes

**Step 5: Implement scale step** — trimesh bounding box, uniform scale, center to origin

**Step 6: Implement boolean cuts** — manifold3d lazy import, flat_bottom plane cut, hole cylinder difference, slot box difference. Wrap in try/except for graceful degradation.

**Step 7: Implement quality validation** — watertight check, volume, bounding box, non-manifold re-check

**Step 8: Run tests**

Run: `uv run pytest tests/test_mesh_post_processor.py -v`
Expected: All PASS

**Step 9: Commit**

```bash
git add backend/core/mesh_post_processor.py tests/test_mesh_post_processor.py
git commit -m "feat(organic): add mesh post-processing pipeline (repair/scale/boolean/validate)"
```

---

### Task 5: OrganicSpec Builder `[backend]` `[test]`

**Files:**
- Create: `backend/core/organic_spec_builder.py`
- Create: `tests/test_organic_spec_builder.py`

**Step 1: Write failing test**

Create `tests/test_organic_spec_builder.py`:
- Test Chinese prompt → English translation + shape_category extraction
- Test bounding box suggestion from shape_category
- Test user-provided bounding box overrides suggestion
- Test engineering_cuts pass through unchanged
- Mock LLM response (no real API calls)

**Step 2: Implement OrganicSpecBuilder**

```python
class OrganicSpecBuilder:
    async def build(self, request: OrganicGenerateRequest) -> OrganicSpec:
        # Call LLM to translate prompt + extract shape info
        llm_result = await self._call_llm(request.prompt)
        return OrganicSpec(
            prompt_en=llm_result["prompt_en"],
            prompt_original=request.prompt,
            shape_category=llm_result["shape_category"],
            suggested_bounding_box=llm_result.get("suggested_bounding_box"),
            final_bounding_box=request.constraints.bounding_box or llm_result.get("suggested_bounding_box"),
            engineering_cuts=list(request.constraints.engineering_cuts),
            quality_mode=request.quality_mode,
        )
```

**Step 3: Run tests → PASS**

**Step 4: Commit**

```bash
git add backend/core/organic_spec_builder.py tests/test_organic_spec_builder.py
git commit -m "feat(organic): add OrganicSpecBuilder with LLM prompt translation"
```

---

### Task 6: Backend API Endpoints `[backend]` `[test]`

**Files:**
- Create: `backend/api/organic.py`
- Create: `backend/models/organic_job.py`
- Modify: `backend/main.py:12-44`
- Create: `tests/test_organic_api.py`

**Step 1: Write failing integration tests**

Create `tests/test_organic_api.py`:
- Test `POST /api/generate/organic` returns SSE stream with correct event sequence
- Test `POST /api/generate/organic/upload` validates MIME type (reject .txt → 422)
- Test `POST /api/generate/organic/upload` validates file size (reject >10MB → 422)
- Test `GET /api/generate/organic/{job_id}` returns job status
- Test `GET /api/generate/organic/{job_id}` with invalid ID → 404
- Test `GET /api/generate/organic/providers` returns provider health
- Test feature-gate: `ORGANIC_ENABLED=false` → 503 on all organic endpoints
- Test SSE events contain standard envelope fields (job_id, status, message, progress)
- Mock all providers to avoid real API calls

**Step 2: Implement organic_job store**

Create `backend/models/organic_job.py` — parallel to `backend/models/job.py`:
```python
class OrganicJobStatus(str, Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"

class OrganicJob(BaseModel):
    job_id: str
    status: OrganicJobStatus = OrganicJobStatus.CREATED
    # ... fields for progress, result, error
```

Plus in-memory store functions: `create_organic_job()`, `get_organic_job()`, `update_organic_job()`.

**Step 3: Implement organic API router**

Create `backend/api/organic.py`:
- Feature-gate dependency: check `settings.organic_enabled`, raise 503 if false
- `POST /generate/organic` — text mode SSE endpoint
- `POST /generate/organic/upload` — image mode with MIME/size validation
- `GET /generate/organic/{job_id}` — job status query
- `GET /generate/organic/providers` — provider health check
- All heavy imports (`manifold3d`, `pymeshlab`) are lazy-loaded inside handler functions

**Step 4: Mount router in main.py**

In `backend/main.py`, after existing router mounts:
```python
from backend.api import organic
app.include_router(organic.router, prefix="/api")
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_organic_api.py -v`
Expected: All PASS

**Step 6: Run existing tests to verify no regression**

Run: `uv run pytest tests/ -v`
Expected: All existing tests still PASS

**Step 7: Commit**

```bash
git add backend/api/organic.py backend/models/organic_job.py backend/main.py tests/test_organic_api.py
git commit -m "feat(organic): add SSE API endpoints with feature-gate and upload validation"
```

---

### Task 7: Navigation Restructure `[frontend]`

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/src/pages/Home/index.tsx`

**Step 1: Restructure sidebar menu**

Modify `frontend/src/layouts/MainLayout.tsx`:

Replace flat `menuItems` with two-level structure:

```tsx
import { ScissorOutlined, BulbOutlined } from '@ant-design/icons';

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  {
    key: 'precision',
    icon: <ExperimentOutlined />,
    label: '精密建模',
    children: [
      { key: '/generate', label: '文本/图纸生成' },
      { key: '/templates', icon: <AppstoreOutlined />, label: '参数化模板' },
      { key: '/standards', icon: <BookOutlined />, label: '工程标准' },
      { key: '/benchmark', icon: <BarChartOutlined />, label: '评测基准' },
    ],
  },
  { key: '/generate/organic', icon: <BulbOutlined />, label: '创意雕塑' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];
```

Fix `selectedKeys` to handle sub-routes:

```tsx
const getSelectedKey = (pathname: string) => {
  if (pathname.startsWith('/benchmark')) return '/benchmark';
  if (pathname.startsWith('/generate/organic')) return '/generate/organic';
  if (pathname.startsWith('/generate')) return '/generate';
  return pathname;
};

const getOpenKeys = (pathname: string) => {
  const precisionPaths = ['/generate', '/templates', '/standards', '/benchmark'];
  if (precisionPaths.some(p => pathname.startsWith(p)) && !pathname.startsWith('/generate/organic')) {
    return ['precision'];
  }
  return [];
};
```

Use `selectedKeys={[getSelectedKey(location.pathname)]}` and `defaultOpenKeys={getOpenKeys(location.pathname)}`.

**Step 2: Update header tagline**

Change `AI 驱动的 2D → 3D CAD 生成平台` to `AI 驱动的 3D 模型生成平台`.

**Step 3: Redesign homepage**

Modify `frontend/src/pages/Home/index.tsx`:
- Two primary cards: 精密建模 → `/generate`, 创意雕塑 → `/generate/organic`
- Three secondary cards: 参数化模板, 工程标准, 评测基准

```tsx
const primaryCards = [
  {
    title: '精密建模',
    description: '上传 2D 工程图纸或输入文本描述，AI 生成精密 3D CAD 模型',
    icon: <ExperimentOutlined style={{ fontSize: 40 }} />,
    path: '/generate',
    gradient: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)',
  },
  {
    title: '创意雕塑',
    description: '输入创意描述或参考图片，AI 生成自由曲面 3D 模型',
    icon: <BulbOutlined style={{ fontSize: 40 }} />,
    path: '/generate/organic',
    gradient: 'linear-gradient(135deg, #722ed1 0%, #b37feb 100%)',
  },
];

const secondaryCards = [
  { title: '参数化模板', icon: <AppstoreOutlined />, path: '/templates', description: '浏览预定义零件模板' },
  { title: '工程标准', icon: <BookOutlined />, path: '/standards', description: '查询行业标准规范' },
  { title: '评测基准', icon: <BarChartOutlined />, path: '/benchmark', description: '运行生成质量评测' },
];
```

**Step 4: Verify navigation**

- All existing routes work
- Sub-route highlighting correct (e.g., `/benchmark/run` highlights 评测基准)
- 精密建模 submenu expands correctly

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: Zero errors

**Step 5: Commit**

```bash
git add frontend/src/layouts/MainLayout.tsx frontend/src/pages/Home/index.tsx
git commit -m "feat(organic): restructure navigation with two-level menu and dual-entry homepage"
```

---

### Task 8: Frontend Organic Generation Page `[frontend]`

**Files:**
- Create: `frontend/src/types/organic.ts`
- Create: `frontend/src/pages/OrganicGenerate/OrganicWorkflow.tsx`
- Create: `frontend/src/contexts/OrganicWorkflowContext.tsx`
- Create: `frontend/src/pages/OrganicGenerate/OrganicInput.tsx`
- Create: `frontend/src/pages/OrganicGenerate/ConstraintForm.tsx`
- Create: `frontend/src/pages/OrganicGenerate/QualitySelector.tsx`
- Create: `frontend/src/pages/OrganicGenerate/MeshStatsCard.tsx`
- Create: `frontend/src/pages/OrganicGenerate/OrganicDownloadButtons.tsx`
- Create: `frontend/src/pages/OrganicGenerate/index.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Create TypeScript types**

Create `frontend/src/types/organic.ts`:

```typescript
export type OrganicJobStatus =
  | 'created'
  | 'analyzing'
  | 'generating'
  | 'post_processing'
  | 'completed'
  | 'failed';

export type OrganicPhase = 'idle' | OrganicJobStatus;

export type QualityMode = 'draft' | 'standard' | 'high';
export type ProviderPreference = 'auto' | 'tripo3d' | 'hunyuan3d';
export type CutType = 'flat_bottom' | 'hole' | 'slot';
export type CutDirection = 'top' | 'bottom' | 'front' | 'back' | 'left' | 'right';

export interface EngineeringCut {
  type: CutType;
  diameter?: number;
  depth?: number;
  width?: number;
  length?: number;
  position?: [number, number, number];
  direction?: CutDirection;
  offset?: number;
}

export interface OrganicConstraints {
  bounding_box: [number, number, number] | null;
  engineering_cuts: EngineeringCut[];
}

export interface MeshStats {
  vertex_count: number;
  face_count: number;
  is_watertight: boolean;
  volume_cm3: number | null;
  bounding_box: Record<string, number>;
  has_non_manifold: boolean;
  repairs_applied: string[];
  boolean_cuts_applied: number;
}

export interface OrganicWorkflowState {
  phase: OrganicPhase;
  jobId: string | null;
  message: string;
  progress: number;
  error: string | null;
  modelUrl: string | null;
  stlUrl: string | null;
  threemfUrl: string | null;
  meshStats: MeshStats | null;
  postProcessStep: string | null;
}

export interface OrganicGenerateRequest {
  prompt: string;
  constraints: OrganicConstraints;
  quality_mode: QualityMode;
  provider: ProviderPreference;
}
```

**Step 2: Create useOrganicWorkflow hook**

Create `frontend/src/pages/OrganicGenerate/OrganicWorkflow.tsx`:
- SSE consumption pattern identical to `GenerateWorkflow.tsx`
- 4-step progress: 分析 → 生成 → 后处理 → 完成
- Handles organic-specific SSE events (analyzing, generating, post_processing, completed)
- `startGenerate(request)` and `startImageGenerate(file, constraints)` callbacks

**Step 3: Create OrganicWorkflowContext**

Create `frontend/src/contexts/OrganicWorkflowContext.tsx`:
- Pattern identical to `GenerateWorkflowContext.tsx`
- Wraps `useOrganicWorkflow()` + constraint/quality state

**Step 4: Create input components**

Create `OrganicInput.tsx`:
- Ant Design `Tabs` with text (TextArea) and image (Upload + Dragger) tabs
- Image upload: accept png/jpeg/webp, max 10MB, preview

Create `ConstraintForm.tsx`:
- Bounding box: 3 InputNumber fields (X, Y, Z mm)
- Engineering cuts: dynamic list with Add/Remove
- Each cut: Select(type) + conditional fields (diameter, depth, width, etc.)

Create `QualitySelector.tsx`:
- Radio.Group for quality_mode (draft/standard/high)
- Select for provider (auto/tripo3d/hunyuan3d)

**Step 5: Create result display components**

Create `MeshStatsCard.tsx`:
- Card with Descriptions showing vertex/face count, watertight status, volume, bbox
- Watertight status with color indicator (green ✓ / red ✗)

Create `OrganicDownloadButtons.tsx`:
- STL and 3MF download buttons, enabled only when URLs available
- Uses `<a href={url} download>` pattern

**Step 6: Create page main component**

Create `frontend/src/pages/OrganicGenerate/index.tsx`:
- Left column: OrganicInput + ConstraintForm + QualitySelector + Generate button + Reset button
- Right column: 4-step progress + Viewer3D + MeshStatsCard + DownloadButtons
- Uses `useOrganicWorkflowContext()` for state

**Step 7: Update App.tsx routing**

In `frontend/src/App.tsx`:
- Import `OrganicWorkflowProvider` and `OrganicGenerate`
- Wrap with both providers
- Add route: `<Route path="/generate/organic" element={<OrganicGenerate />} />`

**Step 8: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: Zero errors

Run: `cd frontend && npm run lint`
Expected: Zero errors

**Step 9: Commit**

```bash
git add frontend/src/types/organic.ts frontend/src/pages/OrganicGenerate/ frontend/src/contexts/OrganicWorkflowContext.tsx frontend/src/App.tsx
git commit -m "feat(organic): add organic generation page with constraint form, SSE workflow, 3D viewer"
```

---

### Task 9: Regression Protection & E2E Verification `[test:e2e]`

**Files:**
- Create: `tests/test_mechanical_regression.py`

**Step 1: Write mechanical pipeline smoke tests**

```python
"""Smoke tests ensuring the mechanical pipeline is unaffected by organic additions."""
import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

async def test_mechanical_text_endpoint_responds(client):
    resp = await client.post("/api/generate", json={"text": "test"})
    assert resp.status_code == 200

async def test_mechanical_drawing_endpoint_responds(client):
    # Multipart with dummy image
    resp = await client.post("/api/generate/drawing", files={"image": ("test.png", b"fake", "image/png")})
    assert resp.status_code in (200, 422)  # 422 for invalid image is acceptable

async def test_organic_feature_gate_disabled(client, monkeypatch):
    monkeypatch.setenv("ORGANIC_ENABLED", "false")
    resp = await client.post("/api/generate/organic", json={"prompt": "test"})
    assert resp.status_code == 503

async def test_health_endpoint_unaffected(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
```

**Step 2: Run regression tests**

Run: `uv run pytest tests/test_mechanical_regression.py -v`
Expected: All PASS

**Step 3: E2E manual verification checklist**

Start services: `./scripts/start-v3.sh`

- [ ] Navigate to `/` — homepage shows dual-entry cards
- [ ] Click 精密建模 → navigates to `/generate`
- [ ] Click 创意雕塑 → navigates to `/generate/organic`
- [ ] Sidebar: 精密建模 has submenu (文本/图纸生成, 模板, 标准, 评测)
- [ ] Sidebar: 创意雕塑 is standalone
- [ ] `/generate/organic`: input area, constraint form, quality selector visible
- [ ] Text-to-3D: enter prompt, set constraints, generate → SSE progress → 3D preview → download
- [ ] Image-to-3D: upload image, generate → SSE progress → 3D preview
- [ ] Navigate away and back — state persisted (Context working)
- [ ] Click 重新开始 — resets to idle
- [ ] Feature-gate: set `ORGANIC_ENABLED=false`, restart → organic endpoints return 503
- [ ] Header tagline: "AI 驱动的 3D 模型生成平台"

**Step 4: Commit**

```bash
git add tests/test_mechanical_regression.py
git commit -m "test(organic): add mechanical pipeline regression tests and E2E checklist"
```

---

## Summary

| Task | Domain | Dependencies | Est. Files |
|------|--------|-------------|-----------|
| 1. Dependencies & Config | `[backend]` | none | 4 modified |
| 2. Data Models | `[backend]` `[test]` | Task 1 | 2 created |
| 3. Provider Layer | `[backend]` `[test]` | Task 2 | 6 created |
| 4. Post-Processing | `[backend]` `[test]` | Task 2 | 2 created |
| 5. Spec Builder | `[backend]` `[test]` | Task 2 | 2 created |
| 6. API Endpoints | `[backend]` `[test]` | Tasks 2-5 | 3 created, 1 modified |
| 7. Navigation | `[frontend]` | none | 2 modified |
| 8. Organic Page | `[frontend]` | Task 7 | 9 created, 1 modified |
| 9. Regression & E2E | `[test:e2e]` | Tasks 6, 8 | 1 created |

**Parallel execution:** Tasks 3/4/5 can run in parallel; Tasks 7/8 can run in parallel with backend tasks.
