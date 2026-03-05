"""LocalModelStrategy — base class for local HTTP model endpoints.

Provides:
- Health check with TTL cache: GET {endpoint}/health
- Generation POST: POST {endpoint}/v1/generate (JSON + base64)
- 503 retry with Retry-After budget check
- Output file saving helper
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any

import httpx

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level health check cache
# ---------------------------------------------------------------------------

_CACHE_TTL = 30  # seconds

# Cache: endpoint -> (result: bool, timestamp: float)
_health_cache: dict[str, tuple[bool, float]] = {}

# 503 retry constants
_RETRY_AFTER_DEFAULT = 30
_RETRY_AFTER_MAX = 120


class LocalModelStrategy(NodeStrategy):
    """Base class for strategies that call a local HTTP model endpoint.

    Subclasses implement execute() and use _check_endpoint_health() and
    _post_generate() to interact with the local model service.
    """

    def __init__(self, config=None):
        super().__init__(config)

    def _check_endpoint_health(self, endpoint: str) -> bool:
        """Check endpoint health via GET {endpoint}/health with TTL cache.

        Returns True if status 200, False otherwise. Results are cached
        for _CACHE_TTL seconds.
        """
        if endpoint in _health_cache:
            cached_result, cached_time = _health_cache[endpoint]
            if time.monotonic() - cached_time < _CACHE_TTL:
                return cached_result

        url = f"{endpoint.rstrip('/')}/health"
        timeout = getattr(self.config, "timeout", 120)
        check_timeout = min(timeout, 5)
        try:
            resp = httpx.get(url, timeout=check_timeout)
            result = resp.status_code == 200
        except Exception as exc:
            logger.warning("Health check failed for %s: %s", url, exc)
            result = False

        _health_cache[endpoint] = (result, time.monotonic())
        return result

    async def _post_generate(
        self,
        endpoint: str,
        image_b64: str | None = None,
        seed: int | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 330,
    ) -> tuple[bytes, str, dict[str, Any]]:
        """POST JSON to {endpoint}/v1/generate.

        Args:
            endpoint: Base URL of the local model service.
            image_b64: Base64-encoded reference image.
            seed: Random seed for reproducibility.
            params: Model-specific generation parameters.
            timeout: Single request timeout in seconds.

        Returns:
            Tuple of (response_bytes, content_type, mesh_meta).
            mesh_meta contains vertices, faces, watertight from response headers.
        """
        url = f"{endpoint.rstrip('/')}/v1/generate"
        body: dict[str, Any] = {"params": params or {}}
        if image_b64 is not None:
            body["image"] = image_b64
        if seed is not None:
            body["seed"] = seed

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)

            # 503 retry logic — GPU busy, single retry with budget check
            if resp.status_code == 503:
                retry_after = self._parse_retry_after(resp)
                if retry_after + timeout > timeout * 2:
                    raise RuntimeError(
                        f"GPU busy, Retry-After={retry_after}s exceeds budget"
                    )
                logger.info("GPU busy, retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                resp = await client.post(url, json=body)

            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "application/octet-stream")
            mesh_meta = {
                "vertices": resp.headers.get("X-Mesh-Vertices"),
                "faces": resp.headers.get("X-Mesh-Faces"),
                "watertight": resp.headers.get("X-Mesh-Watertight", "").lower() == "true",
            }
            return resp.content, content_type, mesh_meta

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> int:
        """Parse Retry-After header with safe defaults."""
        raw = resp.headers.get("Retry-After", "")
        try:
            value = int(raw)
            if value <= 0:
                return _RETRY_AFTER_DEFAULT
            return min(value, _RETRY_AFTER_MAX)
        except (ValueError, TypeError):
            return _RETRY_AFTER_DEFAULT

    @staticmethod
    def _get_image_b64(ctx: Any) -> str | None:
        """Extract reference image as base64 string for GPU server JSON API.

        Data flow:
        1. organic_reference_image (state top-level) = file_id string (from upload)
        2. Strategy reads via ctx.get("organic_reference_image")
        3. Load file from uploads dir -> base64 encode
        """
        import base64 as _b64

        ref = ctx.get("organic_reference_image")
        if ref is None:
            return None
        if isinstance(ref, bytes):
            return _b64.b64encode(ref).decode()
        if isinstance(ref, str) and ref:
            # file_id -> load file from uploads dir
            uploads_dir = Path("outputs") / "organic" / "uploads"
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = uploads_dir / f"{ref}{ext}"
                if candidate.exists():
                    return _b64.b64encode(candidate.read_bytes()).decode()
            # short string = file_id but file missing -> error
            if len(ref) < 100:
                raise RuntimeError(f"Reference image file not found for id: {ref}")
            # long string -> assume already base64
            return ref
        return None

    @staticmethod
    def _save_output(
        data: bytes,
        job_id: str,
        suffix: str = ".glb",
        prefix: str = "generate",
    ) -> str:
        """Save raw mesh bytes to a temp file and return the path."""
        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / prefix
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_id}{suffix}"
        output_path.write_bytes(data)
        return str(output_path)

    @abstractmethod
    async def execute(self, ctx: Any) -> Any:
        """Subclasses implement the actual generation call."""
        ...
