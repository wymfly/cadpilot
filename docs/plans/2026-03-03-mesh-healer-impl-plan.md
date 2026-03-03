# mesh_healer 双通道节点实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `mesh_repair` stub 替换为完整的双通道 `mesh_healer` 节点，建立后续所有双通道节点复用的标准 pattern。

**Architecture:** 单 AlgorithmHealStrategy 内部按缺陷严重度编排多工具升级链（trimesh→PyMeshFix→MeshLib），外部仅暴露 algorithm/neural/auto 三种策略。NeuralHealStrategy 继承 NeuralStrategy 基类，通过 HTTP `/v1/repair` 调用 NKSR。Phase 0 的 `execute_with_fallback()` + `fallback_chain` 处理 auto 模式 fallback。

**Tech Stack:** trimesh (已有), pymeshfix (新增), meshlib (已有), httpx (mock), pydantic v2

**Design docs:**
- `docs/plans/2026-03-03-mesh-healer-design.md` — brainstorming 设计文档
- `openspec/changes/mesh-healer-dual-channel/` — OpenSpec 规范

**Key references:**
- `backend/graph/descriptor.py` — NodeStrategy ABC, NodeDescriptor
- `backend/graph/context.py` — NodeContext, execute_with_fallback(), get_strategy()
- `backend/graph/strategies/neural.py` — NeuralStrategy 基类（health check + TTL cache）
- `backend/graph/configs/neural.py` — NeuralStrategyConfig
- `backend/graph/configs/base.py` — BaseNodeConfig
- `backend/graph/registry.py` — @register_node decorator
- `backend/graph/nodes/mesh_repair.py` — 要被替换的 stub
- `tests/test_neural_strategy.py` — NeuralStrategy 测试 pattern 参考
- `tests/test_graph_builder.py` — builder switch 测试

**Test stub 注意事项:**
- `tests/conftest.py` 的 MetaPathFinder 会自动 stub `manifold3d`、`pymeshlab`、`httpx` 等重型包
- `pymeshfix` 和 `meshlib` **未**在 stub 列表中，测试需 mock 这些包的 import
- trimesh **未**被 stub，但要注意测试中构造 Trimesh 对象的方式

---

### Task 1: [backend] 添加 pymeshfix 依赖 + conftest 更新

**Files:**
- Modify: `pyproject.toml` (添加 pymeshfix)
- Modify: `tests/conftest.py:25-53` (添加 pymeshfix 和 meshlib 到 stub 列表)

**Step 1: 添加 pymeshfix 到项目依赖**

Run: `uv add pymeshfix`

**Step 2: 将 pymeshfix 和 meshlib 添加到 conftest stub 列表**

`tests/conftest.py` 的 `_STUB_ROOTS` 当前不包含 `pymeshfix` 和 `meshlib`。测试环境中这两个包可能未安装，需要加入 stub：

```python
# 在 _STUB_ROOTS 中添加
"pymeshfix",
"meshlib",
"meshlib.mrmeshpy",
```

> meshlib 虽然已在 pyproject.toml 中，但其 C++ 扩展在 CI/轻量环境可能不可用。

**Step 3: 运行测试确认 stub 不破坏现有测试**

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: 所有 13 个测试 PASS

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py
git commit -m "feat(deps): add pymeshfix + update conftest stubs for mesh healing"
```

---

### Task 2: [backend] 诊断模块 — MeshDiagnosis + diagnose()

**Files:**
- Create: `backend/graph/strategies/heal/__init__.py`
- Create: `backend/graph/strategies/heal/diagnose.py`
- Test: `tests/test_mesh_healer.py`

**Step 1: 创建 strategies/heal 包**

`backend/graph/strategies/heal/__init__.py`:
```python
"""Mesh healing strategies — algorithm + neural dual-channel."""
```

**Step 2: 编写诊断模块的失败测试**

`tests/test_mesh_healer.py`:
```python
"""Tests for mesh_healer dual-channel node."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh


class TestMeshDiagnosis:
    """diagnose() 按缺陷严重度分级。"""

    def _make_watertight_box(self) -> trimesh.Trimesh:
        """创建水密立方体用于测试。"""
        return trimesh.primitives.Box().to_mesh()

    def _make_open_mesh(self) -> trimesh.Trimesh:
        """创建有孔洞的非水密 mesh（删除一个面）。"""
        box = trimesh.primitives.Box().to_mesh()
        # 删除最后一个面制造孔洞
        faces = box.faces[:-1]
        return trimesh.Trimesh(vertices=box.vertices, faces=faces)

    def _make_flipped_normals(self) -> trimesh.Trimesh:
        """创建 normals 翻转的 mesh。"""
        box = trimesh.primitives.Box().to_mesh()
        # 翻转所有 face winding
        box.faces = np.fliplr(box.faces)
        return box

    def test_clean_mesh_diagnosed_as_clean(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_watertight_box()
        result = diagnose(mesh)
        assert result.level == "clean"
        assert result.issues == []

    def test_flipped_normals_diagnosed_as_mild(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_flipped_normals()
        result = diagnose(mesh)
        assert result.level in ("mild", "moderate")
        assert len(result.issues) > 0

    def test_open_mesh_diagnosed_as_moderate(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_open_mesh()
        result = diagnose(mesh)
        assert result.level in ("moderate", "severe")
        assert len(result.issues) > 0

    def test_level_is_valid_literal(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_watertight_box()
        result = diagnose(mesh)
        assert result.level in ("clean", "mild", "moderate", "severe")


class TestValidateRepair:
    """validate_repair() 检查修复结果。"""

    def test_watertight_mesh_passes(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        mesh = trimesh.primitives.Box().to_mesh()
        assert validate_repair(mesh) is True

    def test_non_watertight_fails(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        box = trimesh.primitives.Box().to_mesh()
        faces = box.faces[:-1]
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=faces)
        assert validate_repair(mesh) is False

    def test_empty_mesh_fails(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        mesh = trimesh.Trimesh()
        assert validate_repair(mesh) is False
```

**Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_mesh_healer.py::TestMeshDiagnosis -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.graph.strategies.heal'`

**Step 4: 实现诊断模块**

`backend/graph/strategies/heal/diagnose.py`:
```python
"""Mesh diagnosis — analyze defects and grade severity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import trimesh


DefectLevel = Literal["clean", "mild", "moderate", "severe"]


@dataclass
class MeshDiagnosis:
    """Result of mesh defect analysis."""

    level: DefectLevel
    issues: list[str] = field(default_factory=list)


def diagnose(mesh: trimesh.Trimesh) -> MeshDiagnosis:
    """Analyze mesh topology defects, return severity grade.

    Levels:
    - clean: watertight + oriented, no issues
    - mild: normals/winding problems only
    - moderate: holes or non-manifold edges
    - severe: self-intersection or large missing areas
    """
    issues: list[str] = []

    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return MeshDiagnosis(level="severe", issues=["empty mesh"])

    is_wt = mesh.is_watertight

    # Check face orientation consistency via euler_number
    # A closed orientable surface has euler_number == 2
    try:
        euler = mesh.euler_number
        oriented = euler == 2
    except Exception:
        oriented = False

    if is_wt and oriented:
        return MeshDiagnosis(level="clean", issues=[])

    # Check normals consistency
    if not oriented:
        issues.append("inconsistent face orientation")

    # Non-watertight → has holes or non-manifold geometry
    if not is_wt:
        # Count boundary edges (edges appearing in only one face)
        edges = mesh.edges_sorted
        from collections import Counter
        edge_counts = Counter(map(tuple, edges))
        boundary_count = sum(1 for c in edge_counts.values() if c == 1)
        non_manifold_count = sum(1 for c in edge_counts.values() if c > 2)

        if non_manifold_count > 0:
            issues.append(f"{non_manifold_count} non-manifold edges")
        if boundary_count > 0:
            issues.append(f"{boundary_count} boundary edges (holes)")

    # Determine level
    if not is_wt:
        # Check for severe: self-intersection (expensive, use heuristic)
        # Heuristic: if mesh has many non-manifold edges or very low
        # watertight ratio, it's severe
        edges = mesh.edges_sorted
        from collections import Counter
        edge_counts = Counter(map(tuple, edges))
        non_manifold_count = sum(1 for c in edge_counts.values() if c > 2)

        if non_manifold_count > len(mesh.edges_unique) * 0.1:
            return MeshDiagnosis(level="severe", issues=issues)

        return MeshDiagnosis(level="moderate", issues=issues)

    # Watertight but not well-oriented
    return MeshDiagnosis(level="mild", issues=issues)


def validate_repair(mesh: trimesh.Trimesh) -> bool:
    """Check if repaired mesh meets watertight standard.

    Criteria:
    - mesh.is_watertight == True
    - volume > 0
    - has faces (no degenerate mesh)
    """
    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return False
    if not mesh.is_watertight:
        return False
    try:
        vol = mesh.volume
        if vol <= 0:
            return False
    except Exception:
        return False
    return True
```

**Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_mesh_healer.py::TestMeshDiagnosis tests/test_mesh_healer.py::TestValidateRepair -v`
Expected: 所有 7 个测试 PASS

**Step 6: Commit**

```bash
git add backend/graph/strategies/heal/ tests/test_mesh_healer.py
git commit -m "feat(heal): add MeshDiagnosis + diagnose() + validate_repair()"
```

---

### Task 3: [backend] AlgorithmHealStrategy — 升级链

**Files:**
- Create: `backend/graph/strategies/heal/algorithm.py`
- Test: `tests/test_mesh_healer.py` (追加)

**Step 1: 编写 AlgorithmHealStrategy 失败测试**

在 `tests/test_mesh_healer.py` 中追加：
```python
from unittest.mock import patch, MagicMock, AsyncMock


class TestAlgorithmHealStrategy:
    """AlgorithmHealStrategy 升级链测试。"""

    def _make_open_mesh(self) -> trimesh.Trimesh:
        box = trimesh.primitives.Box().to_mesh()
        return trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])

    def _make_mock_ctx(self, mesh: trimesh.Trimesh) -> MagicMock:
        """创建 mock NodeContext。"""
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        mesh.export(tmp.name)
        tmp.close()

        ctx = MagicMock()
        ctx.get_asset.return_value = MagicMock(path=tmp.name)
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()
        ctx.dispatch_progress = AsyncMock()
        ctx.job_id = "test-job"
        ctx.node_name = "mesh_healer"
        ctx.config = MagicMock()
        ctx.config.voxel_resolution = 128
        ctx.config.retopo_threshold = 100000
        return ctx

    @pytest.mark.asyncio
    async def test_clean_mesh_passes_through(self):
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = trimesh.primitives.Box().to_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        # Should have called put_asset with watertight_mesh
        ctx.put_asset.assert_called_once()
        call_args = ctx.put_asset.call_args
        assert call_args[0][0] == "watertight_mesh"

    @pytest.mark.asyncio
    async def test_open_mesh_gets_repaired(self):
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = self._make_open_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        ctx.put_asset.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_progress_events(self):
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = trimesh.primitives.Box().to_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        assert ctx.dispatch_progress.await_count >= 2  # 至少: diagnose + repair
```

**Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_mesh_healer.py::TestAlgorithmHealStrategy -v`
Expected: FAIL

**Step 3: 实现 AlgorithmHealStrategy**

`backend/graph/strategies/heal/algorithm.py`:
```python
"""AlgorithmHealStrategy — diagnosis-driven multi-tool escalation chain.

Escalation levels:
  Level 1: trimesh.repair (normals, winding, basic holes)
  Level 2: PyMeshFix (holes, non-manifold) / PyMeshLab (fallback)
  Level 3: MeshLib voxelization rebuild (self-intersection, severe damage)
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import trimesh

from backend.graph.descriptor import NodeStrategy
from backend.graph.strategies.heal.diagnose import (
    MeshDiagnosis,
    diagnose,
    validate_repair,
)

logger = logging.getLogger(__name__)


class AlgorithmHealStrategy(NodeStrategy):
    """Repair mesh via diagnosis-driven tool escalation."""

    async def execute(self, ctx: Any) -> None:
        # 1. Load mesh
        raw_asset = ctx.get_asset("raw_mesh")
        mesh = trimesh.load(raw_asset.path, force="mesh")
        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
            mesh = trimesh.util.concatenate(meshes) if meshes else trimesh.Trimesh()

        await ctx.dispatch_progress(1, 4, "诊断网格缺陷")

        # 2. Diagnose
        diag = diagnose(mesh)
        logger.info("mesh_healer diagnose: level=%s, issues=%s", diag.level, diag.issues)

        if diag.level == "clean" and validate_repair(mesh):
            await ctx.dispatch_progress(2, 4, "网格无缺陷，跳过修复")
            self._save_result(ctx, mesh, "clean")
            return

        await ctx.dispatch_progress(2, 4, f"修复中 (级别: {diag.level})")

        # 3. Escalation chain
        repaired = self._escalate(mesh, diag)

        await ctx.dispatch_progress(3, 4, "验证修复结果")

        # 4. Save result
        self._save_result(ctx, repaired, diag.level)
        await ctx.dispatch_progress(4, 4, "修复完成")

    def _escalate(self, mesh: trimesh.Trimesh, diag: MeshDiagnosis) -> trimesh.Trimesh:
        """Run escalation chain starting from diagnosed level."""
        levels = {
            "mild": [self._level1_trimesh, self._level2_pymeshfix, self._level3_meshlib],
            "moderate": [self._level2_pymeshfix, self._level3_meshlib],
            "severe": [self._level3_meshlib],
        }
        chain = levels.get(diag.level, [self._level1_trimesh])

        for repair_fn in chain:
            try:
                repaired = repair_fn(mesh)
                if validate_repair(repaired):
                    logger.info("Repair succeeded with %s", repair_fn.__name__)
                    return repaired
                logger.info("Repair by %s did not produce watertight mesh, escalating",
                            repair_fn.__name__)
                mesh = repaired  # pass partially repaired mesh to next level
            except Exception as exc:
                logger.warning("Repair %s failed: %s", repair_fn.__name__, exc)
                continue

        logger.warning("All repair levels exhausted, returning best effort")
        return mesh

    @staticmethod
    def _level1_trimesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Level 1: trimesh built-in repair (normals, winding, basic holes)."""
        mesh = mesh.copy()
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fix_winding(mesh)
        trimesh.repair.fill_holes(mesh)
        return mesh

    @staticmethod
    def _level2_pymeshfix(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Level 2: PyMeshFix (holes + non-manifold edges)."""
        try:
            import pymeshfix
        except ImportError:
            # PyMeshFix not available, try PyMeshLab
            return AlgorithmHealStrategy._level2_pymeshlab(mesh)

        fixer = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
        fixer.repair(verbose=False)
        repaired = trimesh.Trimesh(
            vertices=fixer.v,
            faces=fixer.f,
        )
        logger.info("PyMeshFix repair complete: %d verts, %d faces",
                     len(repaired.vertices), len(repaired.faces))
        return repaired

    @staticmethod
    def _level2_pymeshlab(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Level 2 fallback: PyMeshLab (non-manifold + holes)."""
        try:
            import pymeshlab
            if not hasattr(pymeshlab, "__file__"):
                raise ImportError("pymeshlab is a stub")
        except ImportError:
            raise ImportError("Neither pymeshfix nor pymeshlab available for Level 2")

        import numpy as np
        ms = pymeshlab.MeshSet()
        m = pymeshlab.Mesh(mesh.vertices, mesh.faces)
        ms.add_mesh(m)
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        ms.meshing_close_holes()
        ms.meshing_re_orient_faces_coherently()
        result = ms.current_mesh()
        verts = np.asarray(result.vertex_matrix())
        faces = np.asarray(result.face_matrix())
        if len(verts) == 0:
            raise ValueError("PyMeshLab returned empty mesh")
        return trimesh.Trimesh(vertices=verts, faces=faces)

    @staticmethod
    def _level3_meshlib(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Level 3: MeshLib voxelization rebuild."""
        try:
            import meshlib.mrmeshpy as mr
        except ImportError:
            raise ImportError("meshlib not available for Level 3 repair")

        import numpy as np

        # Convert trimesh → MeshLib
        verts_flat = mesh.vertices.flatten().astype(np.float32)
        faces_flat = mesh.faces.flatten().astype(np.int32)

        mr_mesh = mr.Mesh()
        mr_mesh.points = mr.pointsFromNumpyArray(verts_flat)
        mr_mesh.topology.setTriangles(mr.trianglesFromNumpyArray(faces_flat))

        # Voxelize and reconstruct
        voxel_size = getattr(AlgorithmHealStrategy, '_voxel_resolution', 128)
        bbox = mesh.bounding_box.extents
        max_dim = float(max(bbox))
        voxel_edge = max_dim / voxel_size if voxel_size > 0 else max_dim / 128

        params = mr.MeshToVolumeParams()
        params.surfaceOffset = voxel_edge
        vdb_volume = mr.meshToVolume(mr_mesh, params)

        grid_params = mr.GridToMeshSettings()
        grid_params.voxelSize = voxel_edge
        result_mesh = mr.gridToMesh(vdb_volume, grid_params)

        # Convert back to trimesh
        result_verts = mr.getNumpyVerts(result_mesh)
        result_faces = mr.getNumpyFaces(result_mesh)
        return trimesh.Trimesh(vertices=result_verts, faces=result_faces)

    @staticmethod
    def _save_result(ctx: Any, mesh: trimesh.Trimesh, level: str) -> None:
        """Save repaired mesh to temp file and register as asset."""
        tmp_dir = Path(tempfile.gettempdir()) / "cadpilot" / ctx.job_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_path = tmp_dir / "watertight_mesh.glb"
        mesh.export(str(out_path))

        ctx.put_asset(
            "watertight_mesh",
            str(out_path),
            "glb",
            metadata={
                "is_watertight": mesh.is_watertight,
                "vertex_count": len(mesh.vertices),
                "face_count": len(mesh.faces),
                "repair_level": level,
            },
        )
        ctx.put_data("mesh_repair_status", f"repaired_{level}")
```

**Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_mesh_healer.py::TestAlgorithmHealStrategy -v`
Expected: 3 个测试 PASS

**Step 5: Commit**

```bash
git add backend/graph/strategies/heal/algorithm.py tests/test_mesh_healer.py
git commit -m "feat(heal): add AlgorithmHealStrategy with diagnosis-driven escalation"
```

---

### Task 4: [test] AlgorithmHealStrategy 升级链行为测试

**Files:**
- Modify: `tests/test_mesh_healer.py` (追加升级链测试)

**Step 1: 编写升级链和工具跳级测试**

在 `tests/test_mesh_healer.py` 中追加：
```python
class TestEscalationChain:
    """升级链行为：低级失败→升级到高级；工具不可用→跳过。"""

    def _make_mock_ctx(self, mesh_path: str) -> MagicMock:
        ctx = MagicMock()
        ctx.get_asset.return_value = MagicMock(path=mesh_path)
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()
        ctx.dispatch_progress = AsyncMock()
        ctx.job_id = "test-job"
        ctx.node_name = "mesh_healer"
        ctx.config = MagicMock()
        ctx.config.voxel_resolution = 128
        ctx.config.retopo_threshold = 100000
        return ctx

    @pytest.mark.asyncio
    async def test_level2_used_when_level1_insufficient(self):
        """Level 1 修复后仍非水密 → 自动升级到 Level 2。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        box = trimesh.primitives.Box().to_mesh()
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-2])

        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        mesh.export(tmp.name)
        tmp.close()

        ctx = self._make_mock_ctx(tmp.name)
        strategy = AlgorithmHealStrategy()

        # Mock pymeshfix to succeed where trimesh can't
        with patch("backend.graph.strategies.heal.algorithm.AlgorithmHealStrategy._level2_pymeshfix") as mock_l2:
            fixed = trimesh.primitives.Box().to_mesh()
            mock_l2.return_value = fixed
            await strategy.execute(ctx)
            mock_l2.assert_called()

    @pytest.mark.asyncio
    async def test_skip_level2_when_pymeshfix_unavailable(self):
        """PyMeshFix import 失败 → 跳过 Level 2，尝试 Level 3。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
        from backend.graph.strategies.heal.diagnose import MeshDiagnosis

        box = trimesh.primitives.Box().to_mesh()
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])
        diag = MeshDiagnosis(level="moderate", issues=["holes"])

        with patch.object(AlgorithmHealStrategy, "_level2_pymeshfix",
                          side_effect=ImportError("pymeshfix not found")):
            with patch.object(AlgorithmHealStrategy, "_level3_meshlib",
                              return_value=trimesh.primitives.Box().to_mesh()):
                result = AlgorithmHealStrategy._escalate(
                    AlgorithmHealStrategy(), mesh, diag
                )
                assert result.is_watertight
```

**Step 2: 运行测试**

Run: `uv run pytest tests/test_mesh_healer.py::TestEscalationChain -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_mesh_healer.py
git commit -m "test(heal): add escalation chain behavior tests"
```

---

### Task 5: [backend] NeuralHealStrategy

**Files:**
- Create: `backend/graph/strategies/heal/neural.py`
- Test: `tests/test_mesh_healer.py` (追加)

**Step 1: 编写 NeuralHealStrategy 失败测试**

```python
class TestNeuralHealStrategy:
    """NeuralHealStrategy HTTP 调用测试。"""

    @pytest.mark.asyncio
    async def test_calls_repair_endpoint(self):
        from backend.graph.strategies.heal.neural import NeuralHealStrategy

        strategy = NeuralHealStrategy(config=MagicMock(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
            neural_timeout=60,
            health_check_path="/health",
        ))

        ctx = MagicMock()
        ctx.get_asset.return_value = MagicMock(path="/tmp/raw.glb")
        ctx.put_asset = MagicMock()
        ctx.dispatch_progress = AsyncMock()

        mock_response = {
            "mesh_uri": "/tmp/repaired.obj",
            "metrics": {"is_watertight": True, "holes_filled": 3},
        }

        with patch.object(strategy, "_post", new_callable=AsyncMock,
                          return_value=mock_response):
            await strategy.execute(ctx)

        ctx.put_asset.assert_called_once_with(
            "watertight_mesh",
            "/tmp/repaired.obj",
            "obj",
            metadata={"is_watertight": True, "holes_filled": 3},
        )

    def test_inherits_neural_strategy(self):
        from backend.graph.strategies.heal.neural import NeuralHealStrategy
        from backend.graph.strategies.neural import NeuralStrategy

        assert issubclass(NeuralHealStrategy, NeuralStrategy)
```

**Step 2: 实现 NeuralHealStrategy**

`backend/graph/strategies/heal/neural.py`:
```python
"""NeuralHealStrategy — HTTP-based mesh repair via NKSR model service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.graph.strategies.neural import NeuralStrategy

logger = logging.getLogger(__name__)


class NeuralHealStrategy(NeuralStrategy):
    """Repair mesh via Neural Kernel Surface Reconstruction (NKSR).

    Calls POST /v1/repair on the configured neural endpoint.
    """

    async def _post(self, path: str, payload: dict) -> dict:
        """POST to model service endpoint."""
        endpoint = self.config.neural_endpoint.rstrip("/")
        url = f"{endpoint}{path}"
        timeout = getattr(self.config, "neural_timeout", 60)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def execute(self, ctx: Any) -> None:
        raw_asset = ctx.get_asset("raw_mesh")

        await ctx.dispatch_progress(1, 3, "Neural 修复请求中")

        response = await self._post("/v1/repair", {
            "mesh_uri": raw_asset.path,
        })

        await ctx.dispatch_progress(2, 3, "Neural 修复完成")

        repaired_path = response["mesh_uri"]
        metrics = response.get("metrics", {})

        ctx.put_asset(
            "watertight_mesh",
            repaired_path,
            "obj",
            metadata=metrics,
        )

        await ctx.dispatch_progress(3, 3, "资产注册完成")
```

**Step 3: 运行测试**

Run: `uv run pytest tests/test_mesh_healer.py::TestNeuralHealStrategy -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/graph/strategies/heal/neural.py tests/test_mesh_healer.py
git commit -m "feat(heal): add NeuralHealStrategy with HTTP /v1/repair"
```

---

### Task 6: [backend] MeshHealerConfig

**Files:**
- Create: `backend/graph/configs/mesh_healer.py`
- Test: `tests/test_mesh_healer.py` (追加)

**Step 1: 编写 config 测试**

```python
class TestMeshHealerConfig:
    def test_default_values(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig

        cfg = MeshHealerConfig()
        assert cfg.strategy == "algorithm"
        assert cfg.neural_enabled is False
        assert cfg.voxel_resolution == 128
        assert cfg.retopo_threshold == 100000

    def test_inherits_neural_strategy_config(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from backend.graph.configs.neural import NeuralStrategyConfig

        assert issubclass(MeshHealerConfig, NeuralStrategyConfig)
```

**Step 2: 实现 MeshHealerConfig**

`backend/graph/configs/mesh_healer.py`:
```python
"""Configuration for mesh_healer node."""

from backend.graph.configs.neural import NeuralStrategyConfig


class MeshHealerConfig(NeuralStrategyConfig):
    """mesh_healer node configuration.

    Inherits neural_enabled, neural_endpoint, neural_timeout, health_check_path
    from NeuralStrategyConfig.
    """

    strategy: str = "algorithm"
    voxel_resolution: int = 128
    retopo_threshold: int = 100000
    retopo_enabled: bool = False
    retopo_endpoint: str | None = None
    retopo_target_faces: int = 50000
```

**Step 3: 运行测试**

Run: `uv run pytest tests/test_mesh_healer.py::TestMeshHealerConfig -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/graph/configs/mesh_healer.py tests/test_mesh_healer.py
git commit -m "feat(heal): add MeshHealerConfig extending NeuralStrategyConfig"
```

---

### Task 7: [backend] mesh_healer 节点注册 + retopo

**Files:**
- Delete: `backend/graph/nodes/mesh_repair.py`
- Create: `backend/graph/nodes/mesh_healer.py`
- Test: `tests/test_mesh_healer.py` (追加)

**Step 1: 编写节点注册测试**

```python
class TestMeshHealerNode:
    def test_node_registered_with_strategies(self):
        """mesh_healer 注册了 algorithm + neural 两种策略。"""
        from backend.graph.nodes.mesh_healer import mesh_healer_node

        desc = mesh_healer_node._node_descriptor
        assert desc.name == "mesh_healer"
        assert "algorithm" in desc.strategies
        assert "neural" in desc.strategies
        assert desc.default_strategy == "algorithm"
        assert desc.fallback_chain == ["algorithm", "neural"]
        assert "raw_mesh" in desc.requires
        assert "watertight_mesh" in desc.produces
        assert desc.input_types == ["organic"]

    def test_config_model_is_mesh_healer_config(self):
        from backend.graph.nodes.mesh_healer import mesh_healer_node
        from backend.graph.configs.mesh_healer import MeshHealerConfig

        desc = mesh_healer_node._node_descriptor
        assert desc.config_model is MeshHealerConfig
```

**Step 2: 删除旧 stub，创建新节点**

删除 `backend/graph/nodes/mesh_repair.py`。

创建 `backend/graph/nodes/mesh_healer.py`:
```python
"""mesh_healer — dual-channel mesh repair node.

Replaces the mesh_repair stub. Uses AlgorithmHealStrategy (diagnosis-driven
multi-tool escalation) and NeuralHealStrategy (HTTP /v1/repair via NKSR).
"""

from __future__ import annotations

import logging

from backend.graph.configs.mesh_healer import MeshHealerConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
from backend.graph.strategies.heal.neural import NeuralHealStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="mesh_healer",
    display_name="网格修复",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    input_types=["organic"],
    config_model=MeshHealerConfig,
    strategies={
        "algorithm": AlgorithmHealStrategy,
        "neural": NeuralHealStrategy,
    },
    default_strategy="algorithm",
    fallback_chain=["algorithm", "neural"],
    description="诊断网格缺陷并修复为水密网格，支持 algorithm/neural/auto 三种策略",
)
async def mesh_healer_node(ctx: NodeContext) -> None:
    """Execute mesh healing via strategy dispatch.

    For auto mode, uses ctx.execute_with_fallback() which tries
    algorithm first, falls back to neural if algorithm fails.
    """
    if ctx.config.strategy == "auto":
        await ctx.execute_with_fallback()
    else:
        strategy = ctx.get_strategy()
        await strategy.execute(ctx)

    # Optional retopo sub-step
    config = ctx.config
    if getattr(config, "retopo_enabled", False):
        await _maybe_retopo(ctx, config)


async def _maybe_retopo(ctx: NodeContext, config: MeshHealerConfig) -> None:
    """Run retopo if face count exceeds threshold and retopo is configured."""
    import trimesh

    asset = ctx.get_asset("watertight_mesh")
    mesh = trimesh.load(asset.path, force="mesh")

    if len(mesh.faces) <= config.retopo_threshold:
        return

    if not config.retopo_endpoint:
        logger.warning("Retopo triggered (faces=%d > threshold=%d) but no endpoint configured",
                       len(mesh.faces), config.retopo_threshold)
        return

    logger.info("Running retopo: %d faces > threshold %d", len(mesh.faces), config.retopo_threshold)
    import httpx
    async with httpx.AsyncClient(timeout=config.neural_timeout) as client:
        resp = await client.post(
            f"{config.retopo_endpoint.rstrip('/')}/v1/retopo",
            json={
                "mesh_uri": asset.path,
                "target_faces": config.retopo_target_faces,
            },
        )
        resp.raise_for_status()
        result = resp.json()

    ctx.put_asset(
        "watertight_mesh",
        result["mesh_uri"],
        "obj",
        metadata=result.get("metrics", {}),
    )
```

**Step 3: 运行测试**

Run: `uv run pytest tests/test_mesh_healer.py::TestMeshHealerNode -v`
Expected: PASS

**Step 4: Commit**

```bash
git rm backend/graph/nodes/mesh_repair.py
git add backend/graph/nodes/mesh_healer.py tests/test_mesh_healer.py
git commit -m "feat(heal): replace mesh_repair stub with mesh_healer dual-channel node"
```

---

### Task 8: [test] 更新 TestBuilderSwitch

**Files:**
- Modify: `tests/test_graph_builder.py:87-96` (mesh_repair → mesh_healer)
- Modify: `tests/test_graph_builder.py:114-116` (default builder assertion)

**Step 1: 更新 stub 节点列表**

在 `test_graph_builder.py` 的 `test_new_builder_has_stub_nodes` 方法中：

```python
# 旧：
for stub in ("mesh_repair", "mesh_scale", "boolean_cuts", "export_formats"):
# 新：
for stub in ("mesh_healer", "mesh_scale", "boolean_cuts", "export_formats"):
```

在 `test_default_is_new_builder` 方法中：
```python
# 旧：
assert "mesh_repair" in node_names, "Default should use new builder"
# 新：
assert "mesh_healer" in node_names, "Default should use new builder"
```

**Step 2: 运行 builder 测试**

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: 所有测试 PASS

**Step 3: Commit**

```bash
git add tests/test_graph_builder.py
git commit -m "test(builder): update TestBuilderSwitch for mesh_repair → mesh_healer rename"
```

---

### Task 9: [test] Fallback + Trace 集成测试

**Files:**
- Modify: `tests/test_mesh_healer.py` (追加)

**Step 1: 编写 fallback 集成测试**

```python
class TestFallbackIntegration:
    """algorithm 失败 → auto 模式 fallback 到 neural。"""

    @pytest.mark.asyncio
    async def test_auto_fallback_to_neural(self):
        """algorithm 策略 execute 抛异常 → auto 模式 fallback 到 neural。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        class FailAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                raise RuntimeError("algorithm failed")

        class SuccessNeural(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "neural")

        desc = NodeDescriptor(
            name="test_fallback",
            display_name="Fallback Test",
            fn=lambda ctx: None,
            strategies={"algorithm": FailAlgorithm, "neural": SuccessNeural},
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_fallback": {"strategy": "auto"}},
            "node_trace": [],
        }

        # Replace the node fn to use execute_with_fallback
        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc.fn = fallback_node
        wrapped = builder._wrap_node(desc)
        result = await wrapped(state)

        # Verify fallback trace
        traces = result.get("node_trace", [])
        assert len(traces) == 1
        entry = traces[0]
        assert entry["node"] == "test_fallback"
        assert "fallback" in entry
        fb = entry["fallback"]
        assert fb["fallback_triggered"] is True
        assert fb["strategy_used"] == "neural"
        assert len(fb["strategies_attempted"]) == 2

    @pytest.mark.asyncio
    async def test_auto_algorithm_success_no_fallback(self):
        """algorithm 策略成功 → fallback_triggered=False。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        class SuccessAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "algorithm")

        class SuccessNeural(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "neural")

        desc = NodeDescriptor(
            name="test_no_fallback",
            display_name="No Fallback Test",
            fn=lambda ctx: None,
            strategies={"algorithm": SuccessAlgorithm, "neural": SuccessNeural},
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )

        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc.fn = fallback_node
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_no_fallback": {"strategy": "auto"}},
            "node_trace": [],
        }
        result = await wrapped(state)

        traces = result.get("node_trace", [])
        assert len(traces) == 1
        fb = traces[0]["fallback"]
        assert fb["fallback_triggered"] is False
        assert fb["strategy_used"] == "algorithm"
```

**Step 2: 运行测试**

Run: `uv run pytest tests/test_mesh_healer.py::TestFallbackIntegration -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_mesh_healer.py
git commit -m "test(heal): add fallback integration + trace recording tests"
```

---

### Task 10: [test] 完整回归测试

**Files:** 无新文件

**Step 1: 运行完整测试套件**

Run: `uv run pytest tests/ -v --tb=short`
Expected: 全量 PASS，无回归

**Step 2: 确认 mesh_healer 在 graph 中可编译**

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: 所有 builder 测试 PASS（含更新后的 TestBuilderSwitch）

**Step 3: 确认新测试全量通过**

Run: `uv run pytest tests/test_mesh_healer.py -v`
Expected: 所有 mesh_healer 测试 PASS

**Step 4: 如有失败，修复后 commit**

```bash
git add -A
git commit -m "fix: resolve regression issues from mesh_healer migration"
```
