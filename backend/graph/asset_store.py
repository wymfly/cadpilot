"""AssetStore — abstraction for persistent file storage.

AssetStore.save() returns an opaque URI string. URIs are only valid
for the same store implementation that produced them — do not pass
URIs between different store implementations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AssetStore(Protocol):
    """Protocol for asset persistence backends."""

    def save(
        self, *, job_id: str, name: str, data: bytes, fmt: str,
    ) -> str:
        """Persist data and return an opaque URI string."""
        ...

    def load(self, uri: str) -> bytes:
        """Load file content by URI. Raises FileNotFoundError if missing."""
        ...


class LocalAssetStore:
    """File-system-based AssetStore.

    Workspace priority: explicit parameter > CADPILOT_WORKSPACE env > cwd.
    Files stored at: {workspace}/jobs/{job_id}/{name}.{fmt}
    """

    def __init__(self, workspace: Path | str | None = None) -> None:
        if workspace is not None:
            self._workspace = Path(workspace).resolve()
        elif env := os.environ.get("CADPILOT_WORKSPACE"):
            self._workspace = Path(env).resolve()
        else:
            self._workspace = Path.cwd().resolve()

    def save(
        self, *, job_id: str, name: str, data: bytes, fmt: str,
    ) -> str:
        # Component-level traversal check: reject ".." in any path segment
        for label, value in [("job_id", job_id), ("name", name)]:
            if ".." in value:
                raise ValueError(
                    f"Path escapes workspace boundary: "
                    f"'{label}' contains '..'"
                )

        target = self._workspace / "jobs" / job_id / f"{name}.{fmt}"
        resolved = target.resolve()

        # Belt-and-suspenders: final resolved path must stay inside workspace
        if not str(resolved).startswith(str(self._workspace)):
            raise ValueError(
                f"Path escapes workspace boundary: {resolved} "
                f"is outside {self._workspace}"
            )

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
        return f"file://{resolved}"

    def load(self, uri: str) -> bytes:
        if uri.startswith("file://"):
            path = Path(uri[7:])
        else:
            path = Path(uri)

        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {uri}")
        return path.read_bytes()
