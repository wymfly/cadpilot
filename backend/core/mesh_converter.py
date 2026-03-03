"""Mesh format conversion utility.

Supports OBJ, GLB, STL, 3MF inter-conversion via trimesh.
Same-format passthrough uses shutil.copy2 (preserves metadata).
"""

from __future__ import annotations

import shutil
from pathlib import Path

SUPPORTED_FORMATS: frozenset[str] = frozenset({"obj", "glb", "stl", "3mf"})


def convert_mesh(
    input_path: Path,
    output_format: str,
    output_dir: Path,
) -> Path:
    """Convert a mesh file to the specified format.

    Parameters
    ----------
    input_path:
        Path to the source mesh file.
    output_format:
        Target format (obj, glb, stl, 3mf). Case-insensitive.
    output_dir:
        Directory where the converted file will be written.

    Returns
    -------
    Path to the output file: ``output_dir / {stem}.{format}``.

    Raises
    ------
    ValueError
        If *output_format* is not in :data:`SUPPORTED_FORMATS`.
    """
    fmt = output_format.lower()

    if fmt not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise ValueError(
            f"Unsupported format: {output_format}. "
            f"Supported formats: {supported}"
        )

    output_path = output_dir / f"{input_path.stem}.{fmt}"

    # Same format → direct copy (preserve original file integrity)
    input_suffix = input_path.suffix.lstrip(".").lower()
    if input_suffix == fmt:
        shutil.copy2(input_path, output_path)
        return output_path

    # Different format → trimesh load/export
    import trimesh

    mesh = trimesh.load(str(input_path))
    mesh.export(str(output_path))
    return output_path
