"""Integration tests for organic generation API endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.organic import _get_settings, _require_organic_enabled
from backend.config import Settings
from backend.models.organic_job import (
    OrganicJobStatus,
    clear_organic_jobs,
    create_organic_job,
)


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Clear organic job store before each test."""
    clear_organic_jobs()
    yield
    clear_organic_jobs()


@pytest.fixture
def app():
    """Create test app."""
    from backend.main import app
    return app


@pytest.fixture
async def client(app):
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _disabled_settings() -> Settings:
    """Return Settings with organic disabled."""
    s = MagicMock(spec=Settings)
    s.organic_enabled = False
    return s


# ---------------------------------------------------------------------------
# Feature gate tests
# ---------------------------------------------------------------------------

class TestFeatureGate:
    async def test_organic_disabled_returns_503(self, app, client: AsyncClient) -> None:
        app.dependency_overrides[_get_settings] = _disabled_settings
        try:
            resp = await client.get("/api/generate/organic/providers")
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    async def test_organic_disabled_post_returns_503(self, app, client: AsyncClient) -> None:
        app.dependency_overrides[_get_settings] = _disabled_settings
        try:
            resp = await client.post(
                "/api/generate/organic",
                json={"prompt": "test"},
            )
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.pop(_get_settings, None)


# ---------------------------------------------------------------------------
# Upload validation tests
# ---------------------------------------------------------------------------

class TestUploadValidation:
    async def test_upload_rejects_invalid_mime(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/generate/organic/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 422
        assert "Unsupported file type" in resp.json()["detail"]

    async def test_upload_rejects_oversize_file(self, client: AsyncClient) -> None:
        big_content = b"x" * (11 * 1024 * 1024)
        resp = await client.post(
            "/api/generate/organic/upload",
            files={"file": ("big.png", big_content, "image/png")},
        )
        assert resp.status_code == 422
        assert "File too large" in resp.json()["detail"]

    async def test_upload_accepts_valid_png(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/generate/organic/upload",
            files={"file": ("test.png", b"fake-png-data", "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "file_id" in data
        assert data["filename"] == "test.png"
        assert data["size"] == len(b"fake-png-data")

    async def test_upload_accepts_jpeg(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/generate/organic/upload",
            files={"file": ("test.jpg", b"fake-jpg-data", "image/jpeg")},
        )
        assert resp.status_code == 200

    async def test_upload_accepts_webp(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/generate/organic/upload",
            files={"file": ("test.webp", b"fake-webp-data", "image/webp")},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Job status tests
# ---------------------------------------------------------------------------

class TestJobStatus:
    async def test_get_nonexistent_job_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/generate/organic/no-such-job")
        assert resp.status_code == 404

    async def test_get_existing_job(self, client: AsyncClient) -> None:
        create_organic_job(
            job_id="test-job-1",
            prompt="测试",
            provider="auto",
        )
        resp = await client.get("/api/generate/organic/test-job-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "test-job-1"
        assert data["status"] == "created"
        assert data["progress"] == 0.0


# ---------------------------------------------------------------------------
# Provider health tests
# ---------------------------------------------------------------------------

class TestProviderHealth:
    async def test_providers_endpoint_returns_structure(self, client: AsyncClient) -> None:
        with patch("backend.infra.mesh_providers.tripo.TripoProvider.check_health", new_callable=AsyncMock, return_value=False), \
             patch("backend.infra.mesh_providers.hunyuan.HunyuanProvider.check_health", new_callable=AsyncMock, return_value=False):

            resp = await client.get("/api/generate/organic/providers")
            assert resp.status_code == 200
            data = resp.json()
            assert "providers" in data
            assert "tripo3d" in data["providers"]
            assert "hunyuan3d" in data["providers"]
            assert "default_provider" in data


# ---------------------------------------------------------------------------
# SSE stream tests
# ---------------------------------------------------------------------------

class TestSSEStream:
    async def test_generate_returns_sse_stream(self, client: AsyncClient) -> None:
        """Test that POST /generate/organic returns an SSE event stream."""
        with patch("backend.core.organic_spec_builder.OrganicSpecBuilder.build") as mock_build, \
             patch("backend.api.organic._create_provider") as mock_create_prov, \
             patch("backend.core.mesh_post_processor.MeshPostProcessor.process") as mock_process:

            # Mock spec builder
            mock_spec = MagicMock()
            mock_spec.prompt_en = "test"
            mock_spec.final_bounding_box = (50, 50, 50)
            mock_spec.engineering_cuts = []
            mock_spec.quality_mode = "standard"
            mock_build.return_value = mock_spec

            # Mock provider
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=Path("/tmp/test.glb"))
            mock_create_prov.return_value = mock_provider

            # Mock post-processor
            mock_mesh = MagicMock()
            mock_mesh.export = MagicMock()
            mock_stats = MagicMock()
            mock_stats.model_dump.return_value = {
                "vertex_count": 100,
                "face_count": 200,
                "is_watertight": True,
                "volume_cm3": 1.0,
                "bounding_box": {"x": 50, "y": 50, "z": 50},
                "has_non_manifold": False,
                "repairs_applied": [],
                "boolean_cuts_applied": 0,
            }
            mock_result = MagicMock()
            mock_result.mesh = mock_mesh
            mock_result.stats = mock_stats
            mock_result.warnings = []
            mock_process.return_value = mock_result

            resp = await client.post(
                "/api/generate/organic",
                json={"prompt": "高尔夫球头"},
            )
            assert resp.status_code == 200
            text = resp.text
            assert "event:" in text

    async def test_sse_events_contain_envelope_fields(self, client: AsyncClient) -> None:
        """Verify SSE events have job_id, status, message, progress."""
        with patch("backend.core.organic_spec_builder.OrganicSpecBuilder.build") as mock_build, \
             patch("backend.api.organic._create_provider") as mock_create_prov, \
             patch("backend.core.mesh_post_processor.MeshPostProcessor.process") as mock_process:

            mock_spec = MagicMock()
            mock_spec.prompt_en = "test"
            mock_spec.final_bounding_box = None
            mock_spec.engineering_cuts = []
            mock_spec.quality_mode = "draft"
            mock_build.return_value = mock_spec

            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=Path("/tmp/test.glb"))
            mock_create_prov.return_value = mock_provider

            mock_mesh = MagicMock()
            mock_mesh.export = MagicMock()
            mock_stats = MagicMock()
            mock_stats.model_dump.return_value = {
                "vertex_count": 100, "face_count": 200,
                "is_watertight": True, "volume_cm3": 1.0,
                "bounding_box": {"x": 50, "y": 50, "z": 50},
                "has_non_manifold": False, "repairs_applied": [],
                "boolean_cuts_applied": 0,
            }
            mock_result = MagicMock()
            mock_result.mesh = mock_mesh
            mock_result.stats = mock_stats
            mock_result.warnings = []
            mock_process.return_value = mock_result

            resp = await client.post(
                "/api/generate/organic",
                json={"prompt": "测试对象"},
            )
            lines = resp.text.strip().split("\n")
            data_lines = [l for l in lines if l.startswith("data:")]
            assert len(data_lines) > 0

            for data_line in data_lines:
                payload = json.loads(data_line[len("data:"):].strip())
                assert "job_id" in payload
                assert "status" in payload
                assert "message" in payload
                assert "progress" in payload

    async def test_empty_prompt_without_image_returns_422(self, client: AsyncClient) -> None:
        """Empty prompt and no reference_image should be rejected."""
        resp = await client.post(
            "/api/generate/organic",
            json={"prompt": ""},
        )
        assert resp.status_code == 422

    async def test_completed_event_includes_threemf_url(self, client: AsyncClient) -> None:
        """Completed SSE event should include threemf_url when 3MF export succeeds."""
        from backend.models.organic import MeshStats

        with patch("backend.core.organic_spec_builder.OrganicSpecBuilder.build") as mock_build, \
             patch("backend.api.organic._create_provider") as mock_create_prov, \
             patch("backend.core.mesh_post_processor.MeshPostProcessor") as mock_pp_cls:

            mock_spec = MagicMock()
            mock_spec.prompt_en = "test"
            mock_spec.final_bounding_box = None
            mock_spec.engineering_cuts = []
            mock_spec.quality_mode = "draft"
            mock_build.return_value = mock_spec

            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=Path("/tmp/test.glb"))
            mock_create_prov.return_value = mock_provider

            # Mock post-processor step by step
            mock_mesh = MagicMock()
            mock_mesh.export = MagicMock()
            mock_repair_info = MagicMock()
            mock_repair_info.status = "success"
            mock_repair_info.message = "OK"
            real_stats = MeshStats(
                vertex_count=100,
                face_count=200,
                is_watertight=True,
                volume_cm3=1.0,
                bounding_box={"x": 50, "y": 50, "z": 50},
                has_non_manifold=False,
            )

            mock_pp = MagicMock()
            mock_pp.load_mesh.return_value = mock_mesh
            mock_pp.repair_mesh.return_value = (mock_mesh, mock_repair_info)
            mock_pp.validate_mesh.return_value = real_stats
            mock_pp_cls.return_value = mock_pp

            resp = await client.post(
                "/api/generate/organic",
                json={"prompt": "测试3MF导出"},
            )
            lines = resp.text.strip().split("\n")
            data_lines = [
                l.strip() for l in lines if l.strip().startswith("data:")
            ]
            completed_events = []
            for data_line in data_lines:
                payload = json.loads(data_line[len("data:"):].strip())
                if payload.get("status") == "completed":
                    completed_events.append(payload)

            assert len(completed_events) == 1
            completed = completed_events[0]
            assert "threemf_url" in completed
            assert completed["threemf_url"] is not None
            assert completed["threemf_url"].endswith(".3mf")

    async def test_empty_prompt_with_image_is_accepted(self, client: AsyncClient) -> None:
        """Empty prompt with a reference_image should pass validation (422 only if image not found)."""
        resp = await client.post(
            "/api/generate/organic",
            json={"prompt": "", "reference_image": "00000000-0000-0000-0000-000000000000"},
        )
        # Should NOT be 422 for "prompt required" — it may fail later (image not found) but passes input validation
        assert resp.status_code != 422 or "prompt" not in resp.text.lower()
