# DfAM 3D 热力图 — 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 CADPilot 添加顶点级 DfAM 分析（壁厚 + 悬垂角）和 3D 热力图可视化

**Architecture:** 后端 VertexAnalyzer 逐顶点 ray-casting → GLB 顶点颜色编码 → 前端 ShaderMaterial 渲染 + PrintReport 联动

**Tech Stack:** trimesh + scipy (KD-tree 降采样回映) + pyembree (可选加速) | Three.js ShaderMaterial | glTF COLOR_0 | React + Ant Design

---

## 域标签

| 标签 | 涉及模块 |
|------|---------|
| `[backend]` | vertex_analyzer, format_exporter, graph node, printability |
| `[frontend]` | Viewer3D, ViewControls, HeatmapLegend, PrintReport |
| `[test]` | 后端单元测试, 前端类型检查 |

---

## 并行性分析

| Task | 可并行 | 依赖 | 预期修改文件 |
|------|--------|------|-------------|
| T0 | 否（串行前置） | 无 | vertex_analyzer.py (接口), printability.py, state.py, printability.ts, generate.ts |
| T1 | ✅ | T0 | vertex_analyzer.py (实现), test_vertex_analyzer.py |
| T2 | ✅ | T0 | format_exporter.py, test_dfam_export.py |
| T3 | ✅ | T0 | dfam.py, builder.py, topology.ts |
| T4 | ✅ | T0 | DfamShader.ts, HeatmapLegend.tsx, Viewer3D/index.tsx, ViewControls.tsx |
| T5 | 否 | T4 | IssueList.tsx, Viewer3D/index.tsx, Generate/index.tsx |
| T6 | 否 | T1 | printability.py, geometry_extractor.py |
| T7 | 否（串行收尾） | 全部 | 无新文件 |

**文件交叉矩阵: T1/T2/T3/T4 文件集无交叉，可完全并行。**

---

## Task 0: 接口定义 + 依赖（串行前置）`[backend]` `[frontend]`

**Files:**
- Create: `backend/core/vertex_analyzer.py`
- Modify: `backend/models/printability.py`
- Modify: `backend/graph/state.py`
- Modify: `frontend/src/types/printability.ts`
- Modify: `frontend/src/types/generate.ts`
- Modify: `frontend/src/pages/Generate/GenerateWorkflow.tsx`

### Step 1: 添加 scipy 依赖

Run: `uv add scipy`
Expected: 成功添加到 pyproject.toml + uv.lock

### Step 2: 创建 VertexAnalyzer 接口

Create `backend/core/vertex_analyzer.py`:

```python
"""Vertex-level DfAM analysis — wall thickness + overhang angle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VertexAnalysisResult:
    """Per-vertex analysis results."""
    wall_thickness: np.ndarray      # float64, mm, shape=(n_vertices,)
    overhang_angle: np.ndarray      # float64, degrees, shape=(n_vertices,)
    risk_wall: np.ndarray           # float64, [0,1], 0=danger 1=safe
    risk_overhang: np.ndarray       # float64, [0,1], 0=danger 1=safe
    stats: dict[str, Any] = field(default_factory=dict)


class VertexAnalyzer:
    """Analyze mesh vertices for DfAM metrics.

    Parameters:
        build_direction: Build direction vector, default +Z.
        build_plate_tolerance: Z threshold below which bottom faces
            are considered resting on the build plate (mm).
    """

    SENTINEL_THICKNESS = 999.0  # mm — no opposing surface found

    def __init__(
        self,
        build_direction: tuple[float, float, float] = (0, 0, 1),
        build_plate_tolerance: float = 0.5,
    ) -> None:
        self.build_direction = np.array(build_direction, dtype=np.float64)
        self.build_plate_tolerance = build_plate_tolerance

    def analyze(
        self,
        mesh_path: str,
        min_wall_threshold: float = 1.0,
        max_overhang_threshold: float = 45.0,
        safe_multiple: float = 3.0,
        max_vertices: int = 50_000,
    ) -> VertexAnalysisResult:
        """Run vertex-level wall thickness + overhang analysis.

        Raises no exceptions — returns empty/sentinel results on failure.
        """
        raise NotImplementedError("Implemented in Task 1")
```

### Step 3: 修改 PrintIssue 增加 region 字段

Modify `backend/models/printability.py`, in `PrintIssue` class add after `suggestion`:

```python
    region: Optional[dict] = None  # {"center": [x,y,z], "radius": float}
```

### Step 4: 修改 CadJobState 增加 dfam 字段

Modify `backend/graph/state.py`, in `CadJobState` add after `recommendations`:

```python
    # ── DfAM analysis outputs ──
    dfam_glb_url: str | None
    dfam_stats: dict | None
```

### Step 5: 前端 PrintIssue 类型同步

Modify `frontend/src/types/printability.ts`, in `PrintIssue` interface add:

```typescript
  region?: { center: number[]; radius: number } | null;
```

### Step 6: 前端 WorkflowState 增加 dfamGlbUrl

Modify `frontend/src/pages/Generate/GenerateWorkflow.tsx`:

1. `WorkflowState` 接口增加字段：
```typescript
  dfamGlbUrl: string | null;
```

2. `useGenerateWorkflow` 初始状态增加：
```typescript
  dfamGlbUrl: null,
```

3. `handleSSEEvent` 的 `completed` case 增加提取：
```typescript
  dfamGlbUrl: (evt.dfam_glb_url as string | undefined) ?? null,
```

### Step 7: 验证

Run: `uv run pytest tests/ -q` — 全部通过
Run: `cd frontend && npx tsc --noEmit` — 无错误

### Step 8: 提交

```bash
git add backend/core/vertex_analyzer.py backend/models/printability.py \
        backend/graph/state.py \
        frontend/src/types/printability.ts \
        frontend/src/pages/Generate/GenerateWorkflow.tsx \
        pyproject.toml uv.lock
git commit -m "feat(dfam): add interfaces and scipy dependency for DfAM analysis"
```

---

## Task 1: 顶点级壁厚分析器 `[backend]` `[test]`

**Files:**
- Modify: `backend/core/vertex_analyzer.py` (实现分析逻辑)
- Create: `tests/test_vertex_analyzer.py`

### Step 1: 编写失败测试

Create `tests/test_vertex_analyzer.py`:

```python
"""Tests for vertex-level DfAM analysis."""

import math
import numpy as np
import pytest
import trimesh

from backend.core.vertex_analyzer import VertexAnalyzer, VertexAnalysisResult


def _make_cylinder(outer_r: float = 10.0, inner_r: float = 8.0, height: float = 20.0) -> trimesh.Trimesh:
    """Create a hollow cylinder (OD=2*outer_r, ID=2*inner_r) via boolean."""
    outer = trimesh.creation.cylinder(radius=outer_r, height=height, sections=32)
    inner = trimesh.creation.cylinder(radius=inner_r, height=height, sections=32)
    return trimesh.boolean.difference([outer, inner], engine="blender")


def _make_flat_plate(z: float = 0.0) -> trimesh.Trimesh:
    """A simple box lying flat — normal pointing up (+Z)."""
    return trimesh.creation.box(extents=[20, 20, 2], transform=trimesh.transformations.translation_matrix([0, 0, z + 1]))


class TestWallThickness:
    def test_hollow_cylinder(self, tmp_path):
        mesh = _make_cylinder(outer_r=10, inner_r=8)
        mesh_path = str(tmp_path / "cylinder.stl")
        mesh.export(mesh_path)
        analyzer = VertexAnalyzer()
        result = analyzer.analyze(mesh_path, min_wall_threshold=1.0)
        # Wall thickness should be ~2mm (OD=20, ID=16, wall=2)
        valid = result.wall_thickness[result.wall_thickness < 999.0]
        assert len(valid) > 0
        assert 1.5 < np.median(valid) < 3.0  # ±50% for tessellation

    def test_no_intersection_sentinel(self, tmp_path):
        # Open box — some rays won't find opposing surface
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh_path = str(tmp_path / "box.stl")
        mesh.export(mesh_path)
        analyzer = VertexAnalyzer()
        result = analyzer.analyze(mesh_path)
        # A solid box: rays from exterior vertices hit opposing face
        assert result.wall_thickness.shape[0] == len(mesh.vertices)


class TestOverhangAngle:
    def test_flat_top_surface(self, tmp_path):
        mesh = trimesh.creation.box(extents=[20, 20, 2], transform=trimesh.transformations.translation_matrix([0, 0, 10]))
        mesh_path = str(tmp_path / "plate_high.stl")
        mesh.export(mesh_path)
        analyzer = VertexAnalyzer()
        result = analyzer.analyze(mesh_path)
        # Top face normals point +Z → angle to build direction = 0°
        assert np.any(result.overhang_angle < 10.0)

    def test_bottom_on_build_plate(self, tmp_path):
        # Box at z=0..2: bottom face normal -Z, z≈0 → on build plate → should be 0°
        mesh = trimesh.creation.box(extents=[20, 20, 2], transform=trimesh.transformations.translation_matrix([0, 0, 1]))
        mesh_path = str(tmp_path / "plate_floor.stl")
        mesh.export(mesh_path)
        analyzer = VertexAnalyzer(build_plate_tolerance=0.5)
        result = analyzer.analyze(mesh_path)
        # Bottom vertices (z ≈ 0) with -Z normal should get 0°, not 180°
        bottom_mask = mesh.vertices[:, 2] < 0.5
        bottom_angles = result.overhang_angle[bottom_mask]
        assert np.all(bottom_angles < 10.0), f"Bottom angles: {bottom_angles}"


class TestRiskNormalization:
    def test_below_threshold_is_zero(self, tmp_path):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh_path = str(tmp_path / "box.stl")
        mesh.export(mesh_path)
        analyzer = VertexAnalyzer()
        result = analyzer.analyze(mesh_path, min_wall_threshold=100.0)
        # With threshold=100mm, a 10mm box should have risk ≈ 0
        valid = result.risk_wall[result.wall_thickness < 999.0]
        if len(valid) > 0:
            assert np.mean(valid) < 0.5
```

### Step 2: 运行测试确认失败

Run: `uv run pytest tests/test_vertex_analyzer.py -v`
Expected: FAIL (NotImplementedError)

### Step 3: 实现分析逻辑

Modify `backend/core/vertex_analyzer.py` — 实现 `analyze` 方法:

```python
def analyze(self, mesh_path, min_wall_threshold=1.0, max_overhang_threshold=45.0,
            safe_multiple=3.0, max_vertices=50_000):
    import trimesh

    mesh = trimesh.load(mesh_path, force="mesh")

    # Decimation for large meshes
    original_mesh = None
    if len(mesh.vertices) > max_vertices:
        original_mesh = mesh
        mesh = mesh.simplify_quadric_decimation(max_vertices)

    normals = mesh.vertex_normals
    vertices = mesh.vertices

    # Wall thickness via ray-casting
    wall_thickness = self._compute_wall_thickness(mesh, vertices, normals)

    # Overhang angle
    overhang_angle = self._compute_overhang_angle(vertices, normals)

    # Map back to original mesh if decimated
    if original_mesh is not None:
        from scipy.spatial import cKDTree
        tree = cKDTree(mesh.vertices)
        _, indices = tree.query(original_mesh.vertices)
        wall_thickness = wall_thickness[indices]
        overhang_angle = overhang_angle[indices]
        mesh = original_mesh

    # Normalize risks
    risk_wall = self._normalize_risk(wall_thickness, min_wall_threshold, safe_multiple, invert=False)
    risk_overhang = self._normalize_risk(overhang_angle, max_overhang_threshold, safe_multiple, invert=True)

    stats = {
        "vertices_analyzed": len(mesh.vertices),
        "min_wall_thickness": float(np.min(wall_thickness[wall_thickness < self.SENTINEL_THICKNESS])) if np.any(wall_thickness < self.SENTINEL_THICKNESS) else None,
        "max_overhang_angle": float(np.max(overhang_angle)),
        "vertices_at_risk_wall": int(np.sum(risk_wall < 0.5)),
        "vertices_at_risk_overhang": int(np.sum(risk_overhang < 0.5)),
        "decimation_applied": original_mesh is not None,
    }

    return VertexAnalysisResult(
        wall_thickness=wall_thickness,
        overhang_angle=overhang_angle,
        risk_wall=risk_wall,
        risk_overhang=risk_overhang,
        stats=stats,
    )
```

Private methods:

```python
def _compute_wall_thickness(self, mesh, vertices, normals):
    """Ray-cast along inverted normals to find opposing surfaces."""
    eps = 1e-4
    origins = vertices - normals * eps  # offset to avoid self-hit
    directions = -normals

    locations, index_ray, _ = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=directions, multiple_hits=False
    )

    thickness = np.full(len(vertices), self.SENTINEL_THICKNESS, dtype=np.float64)
    if len(locations) > 0:
        distances = np.linalg.norm(locations - origins[index_ray], axis=1)
        thickness[index_ray] = distances

    return thickness


def _compute_overhang_angle(self, vertices, normals):
    """Angle between vertex normal and build direction."""
    build_dir = self.build_direction / np.linalg.norm(self.build_direction)
    cos_angle = np.clip(np.dot(normals, build_dir), -1.0, 1.0)
    angles = np.degrees(np.arccos(cos_angle))

    # Build plate exception: bottom vertices with -Z normal
    bottom_mask = (vertices[:, 2] <= self.build_plate_tolerance) & (cos_angle < 0)
    angles[bottom_mask] = 0.0

    return angles


@staticmethod
def _normalize_risk(values, threshold, safe_multiple=3.0, invert=False):
    """Normalize to [0,1] risk scale. 0=danger, 1=safe."""
    sentinel_mask = values >= VertexAnalyzer.SENTINEL_THICKNESS
    if invert:
        # For overhang: 0° = safe (1.0), threshold° = danger (0.0)
        risk = 1.0 - np.clip(values / threshold, 0.0, 1.0)
    else:
        # For wall thickness: >= safe_multiple*threshold = safe (1.0), <= threshold = danger (0.0)
        safe_value = threshold * safe_multiple
        risk = np.clip((values - threshold) / (safe_value - threshold), 0.0, 1.0)
    risk[sentinel_mask] = 1.0  # sentinel = no wall = treated as safe
    return risk
```

### Step 4: 运行测试确认通过

Run: `uv run pytest tests/test_vertex_analyzer.py -v`
Expected: PASS（可能因 trimesh boolean 需 blender 跳过 cylinder 测试）

### Step 5: 提交

```bash
git add backend/core/vertex_analyzer.py tests/test_vertex_analyzer.py
git commit -m "feat(dfam): implement vertex-level wall thickness + overhang analysis"
```

---

## Task 2: DfAM GLB 导出 `[backend]` `[test]`

**Files:**
- Modify: `backend/core/format_exporter.py`
- Create: `tests/test_dfam_export.py`

### Step 1: 编写失败测试

Create `tests/test_dfam_export.py`:

```python
"""Tests for DfAM GLB export with vertex colors."""

import numpy as np
import pytest
import trimesh

from backend.core.format_exporter import FormatExporter


class TestDfamGlbExport:
    def test_export_creates_file(self, tmp_path):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        n = len(mesh.vertices)
        risk_wall = np.random.rand(n).astype(np.float64)
        risk_overhang = np.random.rand(n).astype(np.float64)

        output_path = str(tmp_path / "model_dfam.glb")
        exporter = FormatExporter()
        exporter.export_dfam_glb(
            mesh=mesh,
            risk_wall=risk_wall,
            risk_overhang=risk_overhang,
            wall_stats={"analysis_type": "wall_thickness", "threshold": 1.0, "min_value": 0.5, "max_value": 5.0, "vertices_at_risk_count": 10, "vertices_at_risk_percent": 5.0},
            overhang_stats={"analysis_type": "overhang", "threshold": 45.0, "min_value": 0.0, "max_value": 90.0, "vertices_at_risk_count": 20, "vertices_at_risk_percent": 10.0},
            output_path=output_path,
        )
        assert (tmp_path / "model_dfam.glb").exists()

    def test_exported_glb_has_two_named_meshes(self, tmp_path):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        n = len(mesh.vertices)
        output_path = str(tmp_path / "model_dfam.glb")
        exporter = FormatExporter()
        exporter.export_dfam_glb(
            mesh=mesh,
            risk_wall=np.ones(n),
            risk_overhang=np.ones(n),
            wall_stats={"analysis_type": "wall_thickness", "threshold": 1.0, "min_value": 1.0, "max_value": 5.0, "vertices_at_risk_count": 0, "vertices_at_risk_percent": 0.0},
            overhang_stats={"analysis_type": "overhang", "threshold": 45.0, "min_value": 0.0, "max_value": 45.0, "vertices_at_risk_count": 0, "vertices_at_risk_percent": 0.0},
            output_path=output_path,
        )
        # Reload and check
        scene = trimesh.load(output_path)
        if hasattr(scene, 'geometry'):
            names = list(scene.geometry.keys())
            assert "wall_thickness" in names
            assert "overhang" in names
```

### Step 2: 运行测试确认失败

Run: `uv run pytest tests/test_dfam_export.py -v`
Expected: FAIL (AttributeError: 'FormatExporter' object has no attribute 'export_dfam_glb')

### Step 3: 实现 export_dfam_glb

Modify `backend/core/format_exporter.py`, add method to `FormatExporter`:

```python
def export_dfam_glb(
    self,
    mesh: "trimesh.Trimesh",
    risk_wall: np.ndarray,
    risk_overhang: np.ndarray,
    wall_stats: dict,
    overhang_stats: dict,
    output_path: str,
) -> None:
    """Export DfAM GLB with two named meshes and vertex colors.

    Each mesh carries COLOR_0 (R=risk, G=0, B=0, A=255) and per-mesh extras.
    """
    import trimesh as _trimesh

    def _make_colored_mesh(base_mesh, risk_values, name, stats):
        colors = np.zeros((len(risk_values), 4), dtype=np.uint8)
        colors[:, 0] = (risk_values * 255).astype(np.uint8)  # R = risk
        colors[:, 3] = 255  # A = opaque
        colored = _trimesh.Trimesh(
            vertices=base_mesh.vertices.copy(),
            faces=base_mesh.faces.copy(),
            vertex_colors=colors,
        )
        colored.metadata["name"] = name
        colored.metadata["extras"] = stats
        return colored

    wall_mesh = _make_colored_mesh(mesh, risk_wall, "wall_thickness", wall_stats)
    overhang_mesh = _make_colored_mesh(mesh, risk_overhang, "overhang", overhang_stats)

    scene = _trimesh.Scene()
    scene.add_geometry(wall_mesh, node_name="wall_thickness", geom_name="wall_thickness")
    scene.add_geometry(overhang_mesh, node_name="overhang", geom_name="overhang")

    scene.export(output_path, file_type="glb")
```

### Step 4: 运行测试确认通过

Run: `uv run pytest tests/test_dfam_export.py -v`
Expected: PASS

### Step 5: 提交

```bash
git add backend/core/format_exporter.py tests/test_dfam_export.py
git commit -m "feat(dfam): add DfAM GLB export with dual named meshes and vertex colors"
```

---

## Task 3: 管道集成 — analyze_dfam 节点 `[backend]` `[frontend]`

**Files:**
- Create: `backend/graph/nodes/dfam.py`
- Modify: `backend/graph/builder.py`
- Modify: `frontend/src/components/PipelineDAG/topology.ts`

### Step 1: 创建 analyze_dfam 节点

Create `backend/graph/nodes/dfam.py`:

```python
"""DfAM vertex analysis graph node."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.graph.decorators import timed_node
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)


@timed_node("analyze_dfam")
async def analyze_dfam_node(state: CadJobState) -> dict[str, Any]:
    """Run vertex-level DfAM analysis and export heatmap GLB.

    Catches all exceptions internally to ensure pipeline continuity.
    On failure, returns null results and check_printability falls back
    to global-level analysis.
    """
    step_path = state.get("step_path")
    job_id = state.get("job_id", "unknown")

    if not step_path:
        return {
            "dfam_glb_url": None,
            "dfam_stats": None,
            "_reasoning": {"skipped": "no step_path available"},
        }

    try:
        result = await asyncio.to_thread(_run_dfam_analysis, step_path, job_id)
        return result
    except Exception as exc:
        logger.warning("DfAM analysis failed (non-fatal): %s", exc, exc_info=True)
        return {
            "dfam_glb_url": None,
            "dfam_stats": None,
            "_reasoning": {"error": str(exc)},
        }


def _run_dfam_analysis(step_path: str, job_id: str) -> dict[str, Any]:
    """Synchronous DfAM analysis + GLB export (runs in thread)."""
    from pathlib import Path

    from backend.core.format_exporter import FormatExporter
    from backend.core.vertex_analyzer import VertexAnalyzer

    # Convert STEP → temp STL for trimesh
    exporter = FormatExporter()
    stl_path = exporter._step_to_stl_temp(step_path, exporter._default_config())

    # Run vertex analysis
    analyzer = VertexAnalyzer()
    analysis = analyzer.analyze(stl_path)

    # Export DfAM GLB
    import trimesh
    mesh = trimesh.load(stl_path, force="mesh")

    output_dir = Path(f"outputs/{job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    glb_path = str(output_dir / "model_dfam.glb")

    wall_stats = {
        "analysis_type": "wall_thickness",
        "threshold": 1.0,
        "min_value": analysis.stats.get("min_wall_thickness"),
        "max_value": float(analysis.wall_thickness[analysis.wall_thickness < 999.0].max()) if any(analysis.wall_thickness < 999.0) else None,
        "vertices_at_risk_count": analysis.stats.get("vertices_at_risk_wall", 0),
        "vertices_at_risk_percent": round(analysis.stats.get("vertices_at_risk_wall", 0) / max(len(mesh.vertices), 1) * 100, 1),
    }
    overhang_stats = {
        "analysis_type": "overhang",
        "threshold": 45.0,
        "min_value": 0.0,
        "max_value": analysis.stats.get("max_overhang_angle"),
        "vertices_at_risk_count": analysis.stats.get("vertices_at_risk_overhang", 0),
        "vertices_at_risk_percent": round(analysis.stats.get("vertices_at_risk_overhang", 0) / max(len(mesh.vertices), 1) * 100, 1),
    }

    exporter.export_dfam_glb(
        mesh=mesh,
        risk_wall=analysis.risk_wall,
        risk_overhang=analysis.risk_overhang,
        wall_stats=wall_stats,
        overhang_stats=overhang_stats,
        output_path=glb_path,
    )

    # Build URL using the same pattern as convert_preview
    dfam_glb_url = f"/outputs/{job_id}/model_dfam.glb"

    return {
        "dfam_glb_url": dfam_glb_url,
        "dfam_stats": {**analysis.stats, "wall_stats": wall_stats, "overhang_stats": overhang_stats},
        "_reasoning": {
            "vertices_analyzed": analysis.stats.get("vertices_analyzed"),
            "wall_thickness_range": f"{wall_stats.get('min_value')}-{wall_stats.get('max_value')} mm",
            "overhang_range": f"0-{overhang_stats.get('max_value')}°",
            "decimation_applied": analysis.stats.get("decimation_applied", False),
        },
    }
```

### Step 2: 修改 builder.py 插入节点

Modify `backend/graph/builder.py`:

1. Add import:
```python
from backend.graph.nodes.dfam import analyze_dfam_node
```

2. Add node registration (after `check_printability`):
```python
workflow.add_node("analyze_dfam", analyze_dfam_node)
```

3. Change edge `convert_preview → check_printability` chain:
Replace `workflow.add_edge("check_printability", "finalize")` with:
```python
workflow.add_edge("check_printability", "analyze_dfam")
workflow.add_edge("analyze_dfam", "finalize")
```

Note: `analyze_dfam` is placed AFTER `check_printability` (not before) because the analysis is non-blocking and doesn't need to feed into printability checking for MVP. Task 6 will wire the reverse data flow.

### Step 3: 更新 topology.ts

Modify `frontend/src/components/PipelineDAG/topology.ts`:

1. Add node to `ALL_NODES`:
```typescript
{ id: 'analyze_dfam', label: 'DfAM 分析', group: 'postprocess' },
```

2. Add edges to `ALL_EDGES` (replace `check_printability → finalize`):
```typescript
{ source: 'check_printability', target: 'analyze_dfam' },
{ source: 'analyze_dfam', target: 'finalize' },
```
Remove: `{ source: 'check_printability', target: 'finalize' },`

3. Add layout position in `FULL_LAYOUT`:
```typescript
analyze_dfam:          { x: 165, y: 575 },
```
Update `finalize` y to 675:
```typescript
finalize:              { x: 250, y: 675 },
```

4. Update `PATH_NODES` text/drawing paths — insert `'analyze_dfam'` before `'finalize'`:
```typescript
text: ['create_job', 'analyze_intent', 'confirm_with_user',
       'generate_step_text', 'convert_preview', 'check_printability', 'analyze_dfam', 'finalize'],
drawing: ['create_job', 'analyze_vision', 'confirm_with_user',
          'generate_step_drawing', 'convert_preview', 'check_printability', 'analyze_dfam', 'finalize'],
```

### Step 4: 验证

Run: `uv run pytest tests/ -q`
Run: `cd frontend && npx tsc --noEmit`

### Step 5: 提交

```bash
git add backend/graph/nodes/dfam.py backend/graph/builder.py \
        frontend/src/components/PipelineDAG/topology.ts
git commit -m "feat(dfam): integrate analyze_dfam node into pipeline DAG"
```

---

## Task 4: Three.js DfAM 热力图渲染 `[frontend]`

**Files:**
- Create: `frontend/src/components/Viewer3D/DfamShader.ts`
- Create: `frontend/src/components/Viewer3D/HeatmapLegend.tsx`
- Modify: `frontend/src/components/Viewer3D/index.tsx`
- Modify: `frontend/src/components/Viewer3D/ViewControls.tsx`

### Step 1: 创建 DfamShader.ts

Create `frontend/src/components/Viewer3D/DfamShader.ts`:

```typescript
import * as THREE from 'three';

/**
 * Custom ShaderMaterial for DfAM heatmap visualization.
 * Maps vertex color R channel to green→yellow→red gradient.
 * R=0.0 → red (danger), R=0.5 → yellow (warning), R=1.0 → green (safe).
 */
export function createDfamMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: `
      attribute vec4 color;
      varying float vRisk;
      void main() {
        vRisk = color.r;  // R channel = normalized risk [0,1]
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying float vRisk;
      void main() {
        // Colormap: 0.0=red, 0.5=yellow, 1.0=green
        vec3 red    = vec3(0.863, 0.149, 0.149);  // RGB(220,38,38)
        vec3 yellow = vec3(0.918, 0.702, 0.031);  // RGB(234,179,8)
        vec3 green  = vec3(0.133, 0.773, 0.369);  // RGB(34,197,94)

        vec3 color;
        if (vRisk < 0.5) {
          color = mix(red, yellow, vRisk * 2.0);
        } else {
          color = mix(yellow, green, (vRisk - 0.5) * 2.0);
        }
        gl_FragColor = vec4(color, 1.0);
      }
    `,
    vertexColors: true,
  });
}

/** Metadata extracted from DfAM GLB mesh userData. */
export interface DfamMeshMeta {
  analysis_type: 'wall_thickness' | 'overhang';
  threshold: number;
  min_value: number | null;
  max_value: number | null;
  vertices_at_risk_count: number;
  vertices_at_risk_percent: number;
}
```

### Step 2: 创建 HeatmapLegend.tsx

Create `frontend/src/components/Viewer3D/HeatmapLegend.tsx`:

```tsx
import { Typography } from 'antd';

const { Text } = Typography;

interface HeatmapLegendProps {
  type: 'wall_thickness' | 'overhang';
  min: number | null;
  max: number | null;
  threshold: number;
  verticesAtRisk: number;
  verticesAtRiskPercent: number;
}

const GRADIENT = 'linear-gradient(to top, rgb(220,38,38), rgb(234,179,8), rgb(34,197,94))';

export default function HeatmapLegend({
  type, min, max, threshold, verticesAtRisk, verticesAtRiskPercent,
}: HeatmapLegendProps) {
  const unit = type === 'wall_thickness' ? 'mm' : '°';
  const label = type === 'wall_thickness' ? '壁厚' : '悬垂角';

  return (
    <div style={{
      position: 'absolute', right: 16, top: '50%', transform: 'translateY(-50%)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
      background: 'rgba(255,255,255,0.9)', borderRadius: 8, padding: '12px 8px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.12)', zIndex: 10,
    }}>
      <Text strong style={{ fontSize: 11 }}>{label}</Text>
      <div style={{ display: 'flex', gap: 6 }}>
        <div style={{ width: 16, height: 120, borderRadius: 4, background: GRADIENT }} />
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', fontSize: 10 }}>
          <Text type="success">{max != null ? `${max.toFixed(1)}${unit}` : '—'}</Text>
          <Text type="warning">{threshold.toFixed(1)}{unit}</Text>
          <Text type="danger">{min != null ? `${min.toFixed(1)}${unit}` : '—'}</Text>
        </div>
      </div>
      <Text style={{ fontSize: 10, color: '#999' }}>
        {verticesAtRiskPercent.toFixed(1)}% 超限 ({verticesAtRisk})
      </Text>
    </div>
  );
}
```

### Step 3: 修改 ViewControls.tsx

Modify `frontend/src/components/Viewer3D/ViewControls.tsx`:

1. Add `dfamMode` prop and callback:
```typescript
export type DfamMode = 'normal' | 'wall_thickness' | 'overhang';

interface ViewControlsProps {
  wireframe: boolean;
  darkMode?: boolean;
  dfamMode?: DfamMode;
  dfamAvailable?: boolean;
  onWireframeToggle: () => void;
  onViewChange: (position: [number, number, number]) => void;
  onDfamModeChange?: (mode: DfamMode) => void;
}
```

2. Add DfAM toggle buttons (after wireframe button):
```tsx
{dfamAvailable && onDfamModeChange && (
  <>
    <div style={{ width: 1, height: 20, background: darkMode ? '#555' : '#ddd' }} />
    {(['normal', 'wall_thickness', 'overhang'] as DfamMode[]).map((mode) => (
      <Tooltip key={mode} title={mode === 'normal' ? '标准视图' : mode === 'wall_thickness' ? '壁厚热力图' : '悬垂角热力图'}>
        <Button
          size="small"
          type={dfamMode === mode ? 'primary' : 'default'}
          onClick={() => onDfamModeChange(mode)}
        >
          {mode === 'normal' ? '标准' : mode === 'wall_thickness' ? '壁厚' : '悬垂'}
        </Button>
      </Tooltip>
    ))}
  </>
)}
```

### Step 4: 修改 Viewer3D/index.tsx

Modify `frontend/src/components/Viewer3D/index.tsx`:

1. Add imports for DfAM:
```typescript
import { createDfamMaterial, type DfamMeshMeta } from './DfamShader';
import HeatmapLegend from './HeatmapLegend';
import type { DfamMode } from './ViewControls';
```

2. Add `dfamGlbUrl` prop:
```typescript
interface Viewer3DProps {
  modelUrl: string | null;
  dfamGlbUrl?: string | null;
  // ... existing props
}
```

3. Add state for DfAM:
```typescript
const [dfamMode, setDfamMode] = useState<DfamMode>('normal');
const [dfamScene, setDfamScene] = useState<THREE.Group | null>(null);
const [dfamMeta, setDfamMeta] = useState<DfamMeshMeta | null>(null);
const [dfamLoading, setDfamLoading] = useState(false);
```

4. Lazy-load DfAM GLB on first mode switch (useEffect)
5. Toggle mesh visibility based on dfamMode
6. Apply ShaderMaterial to DfAM meshes
7. Show HeatmapLegend when in DfAM mode

### Step 5: 验证

Run: `cd frontend && npx tsc --noEmit`

### Step 6: 提交

```bash
git add frontend/src/components/Viewer3D/DfamShader.ts \
        frontend/src/components/Viewer3D/HeatmapLegend.tsx \
        frontend/src/components/Viewer3D/index.tsx \
        frontend/src/components/Viewer3D/ViewControls.tsx
git commit -m "feat(dfam): add Three.js heatmap shader, legend, and DfAM view toggle"
```

---

## Task 5: PrintReport ↔ Viewer3D 联动 `[frontend]`

**Files:**
- Modify: `frontend/src/components/PrintReport/IssueList.tsx`
- Modify: `frontend/src/components/Viewer3D/index.tsx`
- Modify: `frontend/src/pages/Generate/index.tsx`

### Step 1: IssueList 添加定位按钮

为有 `region` 的 issue 行显示 `AimOutlined` 图标按钮，点击调用 `onLocateIssue(region)`。

### Step 2: Viewer3D 暴露 focusOnRegion

通过 `useImperativeHandle` + `forwardRef` 暴露 `focusOnRegion({center, radius})` 方法。内部实现：camera 动画平移到 `center + direction * radius * 2`，`lookAt(center)`。

### Step 3: Generate 页面连接

用 `useRef<Viewer3DHandle>` 连接 PrintReport 的 `onLocateIssue` 到 Viewer3D 的 `focusOnRegion`。

### Step 4: 验证

Run: `cd frontend && npx tsc --noEmit`

### Step 5: 提交

```bash
git add frontend/src/components/PrintReport/IssueList.tsx \
        frontend/src/components/Viewer3D/index.tsx \
        frontend/src/pages/Generate/index.tsx
git commit -m "feat(dfam): add PrintReport issue click-to-locate camera animation"
```

---

## Task 6: PrintabilityChecker 增强 `[backend]`

**Files:**
- Modify: `backend/core/printability.py`
- Modify: `backend/core/geometry_extractor.py`
- Modify: `tests/test_printability.py`

### Step 1: geometry_extractor 调用 VertexAnalyzer

在 `extract_geometry_from_mesh()` 中，当 mesh 可用时调用 `VertexAnalyzer` 填充 `min_wall_thickness` 和 `max_overhang_angle`。

### Step 2: printability.py 附加 region

在 `PrintabilityChecker.check()` 中，当检测到壁厚/悬垂超限 issue 时，如果 vertex analysis 结果可用，计算超限顶点的质心和包围球作为 `region`。

### Step 3: 更新测试

在 `tests/test_printability.py` 中添加验证 issue 包含 region 字段的测试。

### Step 4: 验证

Run: `uv run pytest tests/test_printability.py -v`

### Step 5: 提交

```bash
git add backend/core/printability.py backend/core/geometry_extractor.py \
        tests/test_printability.py
git commit -m "feat(dfam): enhance PrintabilityChecker with vertex-level region data"
```

---

## Task 7: 集成验证（串行收尾）

### Step 1: 全量后端测试

Run: `uv run pytest tests/ -v`
Expected: 全部通过

### Step 2: 前端类型检查

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

### Step 3: 前端构建

Run: `cd frontend && npm run build`
Expected: 构建成功

### Step 4: 提交

```bash
git add -A
git commit -m "feat(dfam): DfAM 3D heatmap — vertex analysis + GLB export + heatmap UI"
```

---

## G2 关卡评估

### Step 1: 数量条件

| 条件 | 值 | 阈值 | 满足 |
|------|---|------|------|
| 域标签数 | 3 (`[backend]`, `[frontend]`, `[test]`) | ≥ 3 | ✅ |
| 可并行任务数 | 4 (T1, T2, T3, T4) | ≥ 2 | ✅ |
| 总任务数 | 8 (T0-T7) | ≥ 5 | ✅ |

**三条全满足 → 继续 Step 2。**

### Step 2: 文件独立性评估

| 并行任务对 | T1 文件集 | 对方文件集 | 交叉 |
|-----------|-----------|-----------|------|
| T1 ↔ T2 | vertex_analyzer.py(impl), test_vertex_analyzer.py | format_exporter.py, test_dfam_export.py | ❌ 无 |
| T1 ↔ T3 | 同上 | dfam.py, builder.py, topology.ts | ❌ 无 |
| T1 ↔ T4 | 同上 | DfamShader.ts, HeatmapLegend.tsx, Viewer3D/*.tsx, ViewControls.tsx | ❌ 无 |
| T2 ↔ T3 | format_exporter.py, test_dfam_export.py | dfam.py, builder.py, topology.ts | ❌ 无 |
| T2 ↔ T4 | 同上 | 前端文件 | ❌ 无 |
| T3 ↔ T4 | dfam.py, builder.py, topology.ts | Viewer3D 组件 | ❌ 无 |

**全无交叉 → 推荐 Agent Team。**

### Step 3: 执行结构

```
Phase 0（串行）: T0 接口定义 — team lead 执行
Phase 1（并行）: T1 + T2 + T3 + T4 — 4 个 agent 并行
Phase 2（串行）: T5 + T6 — 串行依赖
Phase 3（串行）: T7 集成验证
Phase 4: Review Team
```
