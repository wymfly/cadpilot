"""Tests for parametric preview API (T26).

Tests:
- Template validation (404, 422)
- Successful preview generation (mocked)
- Cache hit returns instantly
- Timeout returns 408
- Cache invalidation
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.v1.preview import _preview_cache, invalidate_preview_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear preview cache before each test."""
    _preview_cache.clear()
    yield
    _preview_cache.clear()


@pytest.fixture()
def client():
    from backend.main import app

    return TestClient(app)


def _mock_render_factory(tmp_path: Path):
    """Create a mock _render_preview that returns a real temp GLB file."""
    call_count = 0

    def mock_render(template_name: str, params: dict) -> str:
        nonlocal call_count
        call_count += 1
        glb = tmp_path / f"preview_{call_count}.glb"
        glb.write_bytes(b"fake glb content")
        return str(glb)

    mock_render.call_count = lambda: call_count  # type: ignore[attr-defined]
    return mock_render


# ===================================================================
# Template validation
# ===================================================================


class TestPreviewValidation:
    def test_unknown_template_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/preview/parametric",
            json={"template_name": "nonexistent_template_xyz", "params": {}},
        )
        assert resp.status_code == 404

    def test_known_template_invalid_params_returns_422(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When params violate constraints, return 422."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = [
            "Parameter 'outer_diameter' value -10 out of range [10, 500]",
        ]
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        resp = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": -10},
            },
        )
        assert resp.status_code == 422


# ===================================================================
# Successful preview (mocked render)
# ===================================================================


class TestPreviewGeneration:
    def test_successful_preview_returns_glb_url(
        self, client: TestClient, monkeypatch, tmp_path,
    ) -> None:
        """Successful render returns a glb_url."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)
        monkeypatch.setattr(
            prev_mod, "_render_preview", _mock_render_factory(tmp_path),
        )

        resp = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": 100},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "glb_url" in data
        assert data["cached"] is False

    def test_different_params_produce_different_urls(
        self, client: TestClient, monkeypatch, tmp_path,
    ) -> None:
        """Different params should produce different preview URLs."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)
        monkeypatch.setattr(
            prev_mod, "_render_preview", _mock_render_factory(tmp_path),
        )

        resp1 = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": 100},
            },
        )
        resp2 = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": 200},
            },
        )
        assert resp1.json()["glb_url"] != resp2.json()["glb_url"]

    def test_render_failure_returns_500(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Render failure returns 500."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        def mock_render_fail(template_name, params):
            raise RuntimeError("CadQuery execution failed")

        monkeypatch.setattr(prev_mod, "_render_preview", mock_render_fail)

        resp = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": 100},
            },
        )
        assert resp.status_code == 500


# ===================================================================
# Timeout
# ===================================================================


class TestPreviewTimeout:
    def test_timeout_returns_408(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When render exceeds 5s, return 408."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        def mock_render_slow(template_name, params):
            import time as _time

            _time.sleep(10)
            return "/tmp/fake.glb"

        monkeypatch.setattr(prev_mod, "_render_preview", mock_render_slow)

        resp = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": {"outer_diameter": 100},
            },
        )
        assert resp.status_code == 408
        # V1 APIError format: {"error": {"code": ..., "message": ...}}
        error_body = resp.json()
        assert "超时" in error_body.get("error", {}).get("message", "")


# ===================================================================
# Cache behavior
# ===================================================================


class TestPreviewCache:
    def test_cache_hit_returns_cached_true(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Pre-populated cache returns cached=True."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        # Pre-populate cache (use float — Pydantic coerces dict[str, float])
        params = {"outer_diameter": 100.0}
        params_hash = hashlib.md5(
            json.dumps(params, sort_keys=True).encode(),
        ).hexdigest()
        cache_key = f"rotational_flange_disk:{params_hash}"
        _preview_cache[cache_key] = "/outputs/preview-cached/model.glb"

        resp = client.post(
            "/api/v1/preview/parametric",
            json={
                "template_name": "rotational_flange_disk",
                "params": params,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True

    def test_cache_prevents_re_render(
        self, client: TestClient, monkeypatch, tmp_path,
    ) -> None:
        """Second request with same params does NOT re-render."""
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        mock_render = _mock_render_factory(tmp_path)
        monkeypatch.setattr(prev_mod, "_render_preview", mock_render)

        payload = {
            "template_name": "rotational_flange_disk",
            "params": {"outer_diameter": 100},
        }

        # First request — renders
        client.post("/api/v1/preview/parametric", json=payload)
        assert mock_render.call_count() == 1

        # Second request — cache hit, no render
        resp2 = client.post("/api/v1/preview/parametric", json=payload)
        assert resp2.status_code == 200
        assert mock_render.call_count() == 1  # NOT 2

    def test_invalidate_by_template(self) -> None:
        _preview_cache["flange:abc"] = "/url/1"
        _preview_cache["flange:def"] = "/url/2"
        _preview_cache["plate:ghi"] = "/url/3"
        count = invalidate_preview_cache("flange")
        assert count == 2
        assert len(_preview_cache) == 1
        assert "plate:ghi" in _preview_cache

    def test_invalidate_all(self) -> None:
        _preview_cache["a:123"] = "/url/a"
        _preview_cache["b:456"] = "/url/b"
        count = invalidate_preview_cache()
        assert count == 2
        assert len(_preview_cache) == 0

    def test_invalidate_empty(self) -> None:
        count = invalidate_preview_cache()
        assert count == 0

    def test_cache_hit_under_50ms(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Cache hit should respond in under 50ms (no rendering)."""
        import time
        from unittest.mock import MagicMock

        import backend.api.v1.preview as prev_mod

        mock_tpl = MagicMock()
        mock_tpl.validate_params.return_value = []
        monkeypatch.setattr(prev_mod, "_get_template", lambda name: mock_tpl)

        # Pre-populate cache
        params = {"outer_diameter": 80.0}
        params_hash = hashlib.md5(
            json.dumps(params, sort_keys=True).encode(),
        ).hexdigest()
        cache_key = f"rotational_flange_disk:{params_hash}"
        _preview_cache[cache_key] = "/outputs/preview-fast/model.glb"

        start = time.monotonic()
        resp = client.post(
            "/api/v1/preview/parametric",
            json={"template_name": "rotational_flange_disk", "params": params},
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert resp.status_code == 200
        assert resp.json()["cached"] is True
        assert elapsed_ms < 50, f"Cache hit took {elapsed_ms:.1f}ms, expected < 50ms"
