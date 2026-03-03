"""PrusaSlicerStrategy — CLI integration for PrusaSlicer.

Calls prusa-slicer in pure-parameter mode (no config file needed).
All hardware parameters (nozzle_diameter, filament_type) are explicitly
passed to avoid extrusion mismatch.
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


class PrusaSlicerStrategy(NodeStrategy):
    """PrusaSlicer CLI execution strategy."""

    def check_available(self) -> bool:
        """Check if PrusaSlicer is available.

        Uses config.prusaslicer_path if set, otherwise falls back to
        shutil.which("prusa-slicer").
        """
        path = getattr(self.config, "prusaslicer_path", None)
        if path:
            return True
        return shutil.which("prusa-slicer") is not None

    def _get_executable(self) -> str:
        """Resolve the PrusaSlicer executable path."""
        path = getattr(self.config, "prusaslicer_path", None)
        if path:
            return path
        found = shutil.which("prusa-slicer")
        if not found:
            raise RuntimeError("PrusaSlicer not found on PATH")
        return found

    async def execute(self, ctx: Any) -> None:
        """Execute PrusaSlicer CLI to generate G-code.

        Steps:
        1. Get mesh path from context (passed by caller)
        2. Build CLI command with all hardware parameters
        3. Run subprocess with timeout
        4. Parse G-code metadata
        5. Register gcode_bundle asset
        """
        config = self.config
        executable = self._get_executable()

        # Mesh path is passed via ctx._slice_input_path (set by node)
        mesh_path = getattr(ctx, "_slice_input_path", None)
        if mesh_path is None:
            # Fallback: try direct asset access
            asset = ctx.get_asset("final_mesh")
            mesh_path = Path(asset.path)

        mesh_path = Path(mesh_path)

        # Output path
        tmp_dir = Path(tempfile.gettempdir()) / "cadpilot" / ctx.job_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_path = tmp_dir / f"{mesh_path.stem}.gcode"

        # Build CLI command
        cmd = [
            executable,
            "--export-gcode",
            "--layer-height", str(config.layer_height),
            "--fill-density", f"{config.fill_density}%",
            "--nozzle-diameter", str(config.nozzle_diameter),
            "--filament-type", config.filament_type,
        ]

        if config.support_material:
            cmd.append("--support-material")

        cmd.extend(["--output", str(output_path)])
        cmd.append(str(mesh_path))

        logger.info("PrusaSlicer CLI: %s", " ".join(cmd))

        await ctx.dispatch_progress(1, 3, "PrusaSlicer 切片中")

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
            await proc.wait()  # Reap child to prevent zombie
            raise RuntimeError(
                f"PrusaSlicer timed out after {config.timeout}s"
            )

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace") if stderr else ""
            raise RuntimeError(
                f"PrusaSlicer exit code {proc.returncode}: {err_msg}"
            )

        await ctx.dispatch_progress(2, 3, "解析 G-code 元数据")

        # Verify output exists
        if not output_path.exists():
            raise RuntimeError(
                f"PrusaSlicer did not produce output file: {output_path}"
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
