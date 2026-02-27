"""Tripo3D mesh generation provider."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

import httpx
from loguru import logger

from backend.infra.mesh_providers.base import MeshProvider
from backend.models.organic import OrganicSpec

_TRIPO_API_BASE = "https://api.tripo3d.ai/v2/openapi"
_POLL_INTERVAL_S = 2.0


class TripoProvider(MeshProvider):
    """Tripo3D cloud API provider for 3D mesh generation."""

    def __init__(
        self,
        api_key: str | None,
        output_dir: Path,
        timeout_s: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._output_dir = output_dir
        self._timeout_s = timeout_s
        self._client = httpx.AsyncClient(
            base_url=_TRIPO_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=30.0,
        )

    async def generate(
        self,
        spec: OrganicSpec,
        reference_image: bytes | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> Path:
        """Generate mesh via Tripo3D: create task → poll → download."""
        if not self._api_key:
            raise RuntimeError("Tripo3D API key not configured")

        # Step 1: Create task
        if reference_image is not None:
            import base64

            img_type = _detect_image_type(reference_image)
            payload: dict[str, object] = {
                "type": "image_to_model",
                "file": {
                    "type": img_type,
                    "data": base64.b64encode(reference_image).decode(),
                },
            }
        else:
            payload: dict[str, object] = {
                "type": "text_to_model",
                "prompt": spec.prompt_en,
            }
        if spec.negative_prompt:
            payload["negative_prompt"] = spec.negative_prompt

        resp = await self._client.post("/task", json=payload)
        resp_data = resp.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"Tripo3D create task failed: {resp_data}")
        task_id = resp_data["data"]["task_id"]
        logger.info("Tripo3D task created: {}", task_id)

        if on_progress:
            on_progress("Task created, generating mesh...", 0.1)

        # Step 2: Poll for completion
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > self._timeout_s:
                raise TimeoutError(
                    f"Tripo3D task {task_id} timed out after {self._timeout_s}s"
                )

            resp = await self._client.get(f"/task/{task_id}")
            poll_data = resp.json()
            status = poll_data.get("data", {}).get("status", "unknown")

            if status == "success":
                output = poll_data["data"]["output"]
                model_url = output.get("pbr_model") or output.get("model")
                if not model_url:
                    raise RuntimeError(
                        f"Tripo3D task {task_id}: no model URL in output: {list(output.keys())}"
                    )
                break
            elif status in ("failed", "cancelled"):
                raise RuntimeError(f"Tripo3D task {task_id} {status}")

            if on_progress:
                progress = min(0.1 + (elapsed / self._timeout_s) * 0.7, 0.8)
                on_progress(f"Generating ({status})...", progress)

            await asyncio.sleep(_POLL_INTERVAL_S)

        if on_progress:
            on_progress("Downloading mesh...", 0.85)

        # Step 3: Download GLB
        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"{task_id}.glb"
        download_resp = await self._client.get(model_url)
        output_path.write_bytes(download_resp.content)

        if on_progress:
            on_progress("Mesh downloaded", 1.0)

        logger.info("Tripo3D mesh saved to {}", output_path)
        return output_path

    async def check_health(self) -> bool:
        """Check if Tripo3D API is reachable."""
        if not self._api_key:
            return False
        try:
            resp = await self._client.get("/user/balance")
            return resp.status_code == 200 and resp.json().get("code") == 0
        except Exception:
            return False


def _detect_image_type(data: bytes) -> str:
    """Detect image format from magic bytes. Returns 'png', 'jpeg', or 'webp'."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "png"  # fallback
