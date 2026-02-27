"""Format exporter: STEP → STL / glTF(GLB) / 3MF.

STL export uses CadQuery natively.  glTF and 3MF go through an
intermediate STL that is loaded by *trimesh* for conversion.
"""

from __future__ import annotations

import os
import tempfile
from typing import Literal

from pydantic import BaseModel


class ExportConfig(BaseModel):
    """Export configuration for format conversion."""

    format: Literal["step", "stl", "3mf", "gltf"] = "stl"
    linear_deflection: float = 0.1
    angular_deflection: float = 0.5


class FormatExporter:
    """Convert STEP files to downstream formats."""

    def export(self, step_path: str, output_path: str, config: ExportConfig) -> None:
        """Export *step_path* to *output_path* in the requested format."""
        if config.format == "stl":
            self._export_stl(step_path, output_path, config)
        elif config.format == "gltf":
            self._export_via_trimesh(step_path, output_path, config, "glb")
        elif config.format == "3mf":
            self._export_via_trimesh(step_path, output_path, config, "3mf")

    def to_gltf_for_preview(self, step_path: str) -> bytes:
        """STEP → GLB bytes for Three.js preview."""
        import trimesh

        stl_path = self._step_to_stl_temp(step_path, ExportConfig())
        try:
            mesh = trimesh.load(stl_path)
            return mesh.export(file_type="glb")  # type: ignore[return-value]
        finally:
            os.unlink(stl_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _export_stl(step_path: str, output_path: str, config: ExportConfig) -> None:
        import cadquery as cq

        shape = cq.importers.importStep(step_path)
        cq.exporters.export(
            shape,
            output_path,
            exportType="STL",
            tolerance=config.linear_deflection,
            angularTolerance=config.angular_deflection,
        )

    def _export_via_trimesh(
        self,
        step_path: str,
        output_path: str,
        config: ExportConfig,
        trimesh_type: str,
    ) -> None:
        import trimesh

        stl_path = self._step_to_stl_temp(step_path, config)
        try:
            mesh = trimesh.load(stl_path)
            mesh.export(output_path, file_type=trimesh_type)
        finally:
            os.unlink(stl_path)

    @staticmethod
    def _step_to_stl_temp(step_path: str, config: ExportConfig) -> str:
        """STEP → temporary STL file, returns temp file path."""
        import cadquery as cq

        shape = cq.importers.importStep(step_path)
        fd, tmp_stl = tempfile.mkstemp(suffix=".stl")
        os.close(fd)
        cq.exporters.export(
            shape,
            tmp_stl,
            exportType="STL",
            tolerance=config.linear_deflection,
            angularTolerance=config.angular_deflection,
        )
        return tmp_stl
