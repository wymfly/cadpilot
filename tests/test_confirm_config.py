"""Task 4: ConfirmRequest pipeline_config_updates + 旧 API 废弃标记。"""

import pytest
from pydantic import ValidationError


class TestConfirmRequestModel:
    def test_with_updates(self):
        from backend.api.v1.jobs import ConfirmRequest

        req = ConfirmRequest(
            confirmed_params={"diameter": 50},
            pipeline_config_updates={"mesh_repair": {"strategy": "trimesh"}},
        )
        assert req.pipeline_config_updates == {"mesh_repair": {"strategy": "trimesh"}}

    def test_without_updates(self):
        from backend.api.v1.jobs import ConfirmRequest

        req = ConfirmRequest(confirmed_params={"diameter": 50})
        assert req.pipeline_config_updates is None

    def test_invalid_format_rejected(self):
        from backend.api.v1.jobs import ConfirmRequest

        with pytest.raises(ValidationError):
            ConfirmRequest(
                confirmed_params={},
                pipeline_config_updates={"mesh_repair": "invalid"},
            )


class TestDeprecationHeaders:
    def test_tooltips_deprecated(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/tooltips")
        assert "Deprecation" in resp.headers

    def test_presets_deprecated(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/presets")
        assert "Deprecation" in resp.headers
