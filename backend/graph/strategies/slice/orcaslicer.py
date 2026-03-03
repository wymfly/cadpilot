"""OrcaSlicerStrategy — CLI integration for OrcaSlicer.

Parameter mapping differs from PrusaSlicer:
- fill_density: no percent sign (e.g., "20" not "20%")
- CLI executable name may differ
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from backend.core.gcode_parser import parse_gcode_metadata
from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)


class OrcaSlicerStrategy(NodeStrategy):
    """OrcaSlicer CLI execution strategy."""

    def check_available(self) -> bool:
        """Check if OrcaSlicer is available.

        Uses config.orcaslicer_path if set, otherwise falls back to
        shutil.which("orca-slicer").
        """
        path = getattr(self.config, "orcaslicer_path", None)
        if path:
            return True
        return shutil.which("orca-slicer") is not None

    def _get_executable(self) -> str:
        """Resolve the OrcaSlicer executable path."""
        path = getattr(self.config, "orcaslicer_path", None)
        if path:
            return path
        found = shutil.which("orca-slicer")
        if not found:
            raise RuntimeError("OrcaSlicer not found on PATH")
        return found

    async def execute(self, ctx: Any) -> None:
        """Execute OrcaSlicer CLI to generate G-code.

        Similar to PrusaSlicer but with OrcaSlicer-specific parameter mapping:
        - fill_density uses integer without percent sign
        """
        config = self.config
        executable = self._get_executable()

        # Mesh path from node
        mesh_path = getattr(ctx, "_slice_input_path", None)
        if mesh_path is None:
            asset = ctx.get_asset("final_mesh")
            mesh_path = Path(asset.path)

        mesh_path = Path(mesh_path)

        # Output path
        tmp_dir = Path(tempfile.gettempdir()) / "cadpilot" / ctx.job_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_path = tmp_dir / f"{mesh_path.stem}.gcode"

        # Build CLI command (OrcaSlicer parameter format)
        cmd = [
            executable,
            "--export-gcode",
            "--layer-height", str(config.layer_height),
            "--fill-density", str(config.fill_density),  # No % for OrcaSlicer
            "--nozzle-diameter", str(config.nozzle_diameter),
            "--filament-type", config.filament_type,
        ]

        if config.support_material:
            cmd.append("--support-material")

        cmd.extend(["--output", str(output_path)])
        cmd.append(str(mesh_path))

        logger.info("OrcaSlicer CLI: %s", " ".join(cmd))

        await ctx.dispatch_progress(1, 3, "OrcaSlicer 切片中")

        # Execute subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=config.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass  # Best-effort reap; OS will clean up
            raise RuntimeError(
                f"OrcaSlicer timed out after {config.timeout}s"
            )

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace") if stderr else ""
            raise RuntimeError(
                f"OrcaSlicer exit code {proc.returncode}: {err_msg}"
            )

        await ctx.dispatch_progress(2, 3, "解析 G-code 元数据")

        # Verify output exists
        if not output_path.exists():
            raise RuntimeError(
                f"OrcaSlicer did not produce output file: {output_path}"
            )

        # Parse metadata
        metadata = parse_gcode_metadata(output_path)

        # Register asset
        ctx.put_asset(
            "gcode_bundle",
            str(output_path),
            "gcode",
            metadata=metadata,
        )

        await ctx.dispatch_progress(3, 3, "切片完成")
