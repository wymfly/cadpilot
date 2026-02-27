"""Hunyuan3D mesh generation provider (Tencent Cloud)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

import httpx
from loguru import logger

from backend.infra.mesh_providers.base import MeshProvider
from backend.models.organic import OrganicSpec

_HUNYUAN_API_BASE = "https://hunyuan3d.tencentcloudapi.com"
_POLL_INTERVAL_S = 2.0


class HunyuanProvider(MeshProvider):
    """Hunyuan3D (Tencent Cloud) provider for 3D mesh generation."""

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
            base_url=_HUNYUAN_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=30.0,
        )

    async def generate(
        self,
        spec: OrganicSpec,
        reference_image: bytes | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> Path:
        """Generate mesh via Hunyuan3D: submit → poll → download."""
        if not self._api_key:
            raise RuntimeError("Hunyuan3D API key not configured")

        # Step 1: Submit generation task
        is_image_task = reference_image is not None
        if is_image_task:
            import base64

            payload: dict[str, object] = {
                "Action": "SubmitImageTo3DTask",
                "ImageBase64": base64.b64encode(reference_image).decode(),
            }
        else:
            payload: dict[str, object] = {
                "Action": "SubmitTextTo3DTask",
                "Prompt": spec.prompt_en,
            }

        resp = await self._client.post("/", json=payload)
        resp_data = resp.json()
        task_id = resp_data.get("Response", {}).get("TaskId")
        if not task_id:
            raise RuntimeError(f"Hunyuan3D create task failed: {resp_data}")
        logger.info("Hunyuan3D task created: {}", task_id)

        if on_progress:
            on_progress("Task created, generating mesh...", 0.1)

        # Step 2: Poll for completion
        poll_action = "QueryImageTo3DTask" if is_image_task else "QueryTextTo3DTask"
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > self._timeout_s:
                raise TimeoutError(
                    f"Hunyuan3D task {task_id} timed out after {self._timeout_s}s"
                )

            poll_resp = await self._client.get(
                "/", params={"Action": poll_action, "TaskId": task_id}
            )
            poll_data = poll_resp.json()
            status = poll_data.get("Response", {}).get("Status", "UNKNOWN")

            if status == "SUCCEED":
                model_url = poll_data["Response"]["ResultUrl"]
                break
            elif status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Hunyuan3D task {task_id} {status}")

            if on_progress:
                progress = min(0.1 + (elapsed / self._timeout_s) * 0.7, 0.8)
                on_progress(f"Generating ({status})...", progress)

            await asyncio.sleep(_POLL_INTERVAL_S)

        if on_progress:
            on_progress("Downloading mesh...", 0.85)

        # Step 3: Download model
        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"{task_id}.glb"
        download_resp = await self._client.get(model_url)
        output_path.write_bytes(download_resp.content)

        if on_progress:
            on_progress("Mesh downloaded", 1.0)

        logger.info("Hunyuan3D mesh saved to {}", output_path)
        return output_path

    async def check_health(self) -> bool:
        """Check if Hunyuan3D API is reachable."""
        if not self._api_key:
            return False
        try:
            resp = await self._client.get(
                "/", params={"Action": "DescribeServiceStatus"}
            )
            return resp.status_code == 200
        except Exception:
            return False
