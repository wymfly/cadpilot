"""MeshLibShellStrategy — SDF offset shelling via MeshLib."""

from __future__ import annotations

import asyncio
import logging
import math
import tempfile
from pathlib import Path
from typing import Any

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)


def _compute_adaptive_resolution(bbox_max: float, wall_thickness: float) -> int:
    """Compute adaptive voxel resolution.

    Formula: min(512, max(256, ceil(bbox_max / wall_thickness * 5)))
    Ensures >= 5 voxels across wall thickness, capped at 512 to prevent OOM.
    """
    raw = math.ceil(bbox_max / wall_thickness * 5)
    return min(512, max(256, raw))


class MeshLibShellStrategy(NodeStrategy):
    """SDF offset shelling using MeshLib boolean operations."""

    async def execute(self, ctx: Any) -> None:
        """Execute SDF-based mesh shelling."""
        config = ctx.config
        wall_thickness = config.wall_thickness
        voxel_resolution = config.voxel_resolution

        asset = ctx.get_asset("scaled_mesh")
        await ctx.dispatch_progress(1, 5, "加载网格")

        result_path, actual_resolution = await asyncio.to_thread(
            self._shell_sync,
            asset.path,
            wall_thickness,
            voxel_resolution,
            ctx.job_id,
        )

        ctx.put_asset(
            "shelled_mesh", result_path, "mesh",
            metadata={
                "wall_thickness": wall_thickness,
                "voxel_resolution": actual_resolution,
                "shelled": True,
            },
        )
        await ctx.dispatch_progress(5, 5, "抽壳完成")

    @staticmethod
    def _shell_sync(
        mesh_path: str,
        wall_thickness: float,
        voxel_resolution: int,
        job_id: str,
    ) -> tuple[str, int]:
        """Synchronous shelling — runs in thread. Returns (path, actual_resolution)."""
        import trimesh

        mesh = trimesh.load(mesh_path, force="mesh")

        # Compute adaptive resolution if needed
        if voxel_resolution <= 0:
            bbox_max = float(max(mesh.bounding_box.extents))
            voxel_resolution = _compute_adaptive_resolution(bbox_max, wall_thickness)
            logger.info("shell_node: adaptive resolution = %d", voxel_resolution)

        try:
            import meshlib.mrmeshpy as mr

            # 1. Convert trimesh -> MeshLib
            mr_mesh = _trimesh_to_meshlib(mesh)

            # 2. Compute SDF volume
            voxel_size = float(max(mesh.bounding_box.extents)) / voxel_resolution
            params = mr.MeshToVolumeParams()
            params.surfaceOffset = voxel_size * 3
            params.voxelSize = voxel_size
            volume = mr.meshToVolume(mr_mesh, params)

            # 3. Extract inner wall at offset = -wall_thickness
            inner_params = mr.VolumeToMeshByDualMarchingCubesParams()
            inner_params.iso = -wall_thickness
            inner_mesh = mr.volumeToMeshByDualMarchingCubes(volume, inner_params)

            # 4. Boolean difference: outer - inner = hollow shell
            result = mr.boolean(mr_mesh, inner_mesh, mr.BooleanOperation.DifferenceAB)

            # 5. Convert back to trimesh and verify
            result_trimesh = _meshlib_to_trimesh(result.mesh, trimesh)

            if not result_trimesh.is_watertight:
                raise RuntimeError(
                    "shell_node: 抽壳结果非水密（non-watertight），"
                    "后续布尔操作将失败。请调整 voxel_resolution 或 wall_thickness。"
                )

            # 使用绝对值比较（防止反向法线 mesh 的 volume 为负数误判）
            original_vol = abs(mesh.volume) if mesh.volume != 0 else 1e-10
            result_vol = abs(result_trimesh.volume)
            volume_ratio = result_vol / original_vol
            if volume_ratio < 0.05:
                raise RuntimeError(
                    f"Shell result volume is only {volume_ratio:.1%} of original — "
                    "likely boolean operation failure. Try increasing voxel_resolution."
                )

            # 6. Export
            output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "shell"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"{job_id}_shelled.glb")
            result_trimesh.export(output_path)
            return output_path, voxel_resolution

        except ImportError:
            raise RuntimeError(
                "meshlib not installed. Install with: pip install meshlib"
            )


def _trimesh_to_meshlib(mesh):
    """Convert trimesh.Trimesh to meshlib mr.Mesh.

    必须使用 meshlib.mrmeshnumpy 桥接模块，mrmeshpy.meshFromFacesVerts
    不接受 NumPy 数组（需要 C++ vector 类型）。
    """
    import numpy as np
    import meshlib.mrmeshnumpy as mrmeshnumpy
    verts = np.array(mesh.vertices, dtype=np.float32)
    faces = np.array(mesh.faces, dtype=np.int32)
    return mrmeshnumpy.meshFromFacesVerts(faces, verts)


def _meshlib_to_trimesh(mr_mesh, trimesh_mod):
    """Convert meshlib mr.Mesh to trimesh.Trimesh."""
    import meshlib.mrmeshnumpy as mrmeshnumpy
    verts = mrmeshnumpy.getNumpyVerts(mr_mesh)
    faces = mrmeshnumpy.getNumpyFaces(mr_mesh.topology)
    return trimesh_mod.Trimesh(vertices=verts, faces=faces)
