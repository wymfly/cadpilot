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
        # 1. Load mesh — bridge upstream contract
        # Note: AssetRegistry.get() raises KeyError when key not found.
        try:
            raw_asset = ctx.get_asset("raw_mesh")
            mesh_path = raw_asset.path
        except KeyError:
            mesh_path = ctx.get_data("raw_mesh_path")
            if mesh_path is None:
                raise ValueError("No raw mesh found in assets or data")
        mesh = trimesh.load(mesh_path, force="mesh")

        self._voxel_resolution = getattr(ctx.config, "voxel_resolution", 128)

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
        """Run escalation chain starting from diagnosed level.

        Raises RuntimeError when all levels exhausted — this allows:
        - Non-auto mode: error propagates to user
        - Auto mode: execute_with_fallback() catches it and tries neural
        """
        if diag.level == "clean":
            return mesh

        levels = {
            "mild": [self._level1_trimesh, self._level2_pymeshfix, self._level3_meshlib],
            "moderate": [self._level2_pymeshfix, self._level3_meshlib],
            "severe": [self._level3_meshlib],
        }
        chain = levels.get(diag.level, [self._level1_trimesh])

        for repair_fn in chain:
            fn_name = getattr(repair_fn, '__name__', repr(repair_fn))
            try:
                repaired = repair_fn(mesh)
                if validate_repair(repaired):
                    logger.info("Repair succeeded with %s", fn_name)
                    return repaired
                logger.info("Repair by %s did not produce watertight mesh, escalating",
                            fn_name)
                mesh = repaired  # pass partially repaired mesh to next level
            except Exception as exc:
                logger.warning("Repair %s failed: %s", fn_name, exc)
                continue

        raise RuntimeError(
            f"All algorithm repair levels exhausted for {diag.level} mesh. "
            f"Issues: {diag.issues}"
        )

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

    def _level3_meshlib(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Level 3: MeshLib voxelization rebuild."""
        try:
            import meshlib.mrmeshpy as mr
        except ImportError:
            raise ImportError("meshlib not available for Level 3 repair")

        import numpy as np

        # Convert trimesh -> MeshLib
        verts_flat = mesh.vertices.flatten().astype(np.float32)
        faces_flat = mesh.faces.flatten().astype(np.int32)

        mr_mesh = mr.Mesh()
        mr_mesh.points = mr.pointsFromNumpyArray(verts_flat)
        mr_mesh.topology.setTriangles(mr.trianglesFromNumpyArray(faces_flat))

        # Voxelize and reconstruct
        voxel_size = self._voxel_resolution
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
        ctx.put_data("mesh_healer_status", f"repaired_{level}")
