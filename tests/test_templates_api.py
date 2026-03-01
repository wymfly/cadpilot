"""Tests for template management API routes (Phase 3 Task 3.5).

Validates:
- GET    /templates           list all + part_type filter
- GET    /templates/{name}    get single, 404
- POST   /templates           create, 409 duplicate
- PUT    /templates/{name}    update, 404
- DELETE /templates/{name}    delete, 404
- POST   /templates/{name}/validate   valid params, invalid params, 404
- API key authentication on write endpoints (POST/PUT/DELETE)

Tests call the async handler functions directly (via ``asyncio.run``) to
avoid dependency on ``httpx``/``TestClient`` which is stubbed in conftest.
"""

from __future__ import annotations

import asyncio
import textwrap
from unittest.mock import patch

import pytest

import backend.api.v1.templates as tmpl_api
from backend.api.v1.errors import APIError, ErrorCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_tmp_templates(tmp_path, monkeypatch):
    """Point API to a tmp directory with a single test template."""
    yaml_content = textwrap.dedent("""\
        name: test_disk
        display_name: 测试圆盘
        part_type: rotational
        description: 测试用模板
        params:
          - name: diameter
            display_name: 直径
            unit: mm
            param_type: float
            range_min: 10
            range_max: 500
            default: 100
        constraints:
          - "diameter > 0"
        code_template: |
          import cadquery as cq
          result = cq.Workplane("XY").circle({{ diameter }}/2).extrude(10)
          cq.exporters.export(result, "{{ output_filename }}")
    """)
    (tmp_path / "test_disk.yaml").write_text(yaml_content, encoding="utf-8")
    monkeypatch.setattr(tmpl_api, "_TEMPLATES_DIR", tmp_path)


# ---------------------------------------------------------------------------
# GET /templates — list
# ---------------------------------------------------------------------------


class TestListTemplates:
    def test_list_all(self) -> None:
        result = asyncio.run(tmpl_api.list_templates())
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["name"] == "test_disk"

    def test_list_filter_by_type(self) -> None:
        result = asyncio.run(tmpl_api.list_templates(part_type="rotational"))
        assert all(t["part_type"] == "rotational" for t in result)

    def test_list_filter_empty(self) -> None:
        result = asyncio.run(tmpl_api.list_templates(part_type="nonexistent"))
        assert result == []


# ---------------------------------------------------------------------------
# GET /templates/{name} — get single
# ---------------------------------------------------------------------------


class TestGetTemplate:
    def test_get_existing(self) -> None:
        result = asyncio.run(tmpl_api.get_template("test_disk"))
        assert result["name"] == "test_disk"
        assert "params" in result

    def test_get_not_found(self) -> None:
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.get_template("nonexistent"))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /templates — create
# ---------------------------------------------------------------------------


class TestCreateTemplate:
    def test_create_new(self) -> None:
        new = {
            "name": "new_plate",
            "display_name": "新板件",
            "part_type": "plate",
            "description": "test create",
            "params": [
                {
                    "name": "w",
                    "display_name": "宽",
                    "param_type": "float",
                    "default": 50,
                }
            ],
            "code_template": (
                "import cadquery as cq\n"
                "result = cq.Workplane('XY').box({{ w }}, 10, 5)\n"
                "cq.exporters.export(result, '{{ output_filename }}')"
            ),
        }
        result = asyncio.run(tmpl_api.create_template(new))
        assert result["name"] == "new_plate"

        # Verify it's readable afterwards.
        got = asyncio.run(tmpl_api.get_template("new_plate"))
        assert got["name"] == "new_plate"

    def test_create_duplicate_fails(self) -> None:
        dup = {
            "name": "test_disk",
            "display_name": "重复",
            "part_type": "rotational",
            "code_template": "...",
        }
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.create_template(dup))
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# PUT /templates/{name} — update
# ---------------------------------------------------------------------------


class TestUpdateTemplate:
    def test_update_existing(self) -> None:
        update_body = {
            "name": "test_disk",
            "display_name": "更新后",
            "part_type": "rotational",
            "params": [
                {
                    "name": "diameter",
                    "display_name": "直径",
                    "param_type": "float",
                    "default": 200,
                }
            ],
            "code_template": (
                "import cadquery as cq\n"
                "result = cq.Workplane('XY').circle({{ diameter }}/2).extrude(10)\n"
                "cq.exporters.export(result, '{{ output_filename }}')"
            ),
        }
        result = asyncio.run(tmpl_api.update_template("test_disk", update_body))
        assert result["display_name"] == "更新后"

    def test_update_not_found(self) -> None:
        body = {
            "name": "ghost",
            "display_name": "幽灵",
            "part_type": "general",
            "code_template": "...",
        }
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.update_template("ghost", body))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /templates/{name}
# ---------------------------------------------------------------------------


class TestDeleteTemplate:
    def test_delete_existing(self) -> None:
        result = asyncio.run(tmpl_api.delete_template("test_disk"))
        assert result["status"] == "deleted"

        # Verify it's gone.
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.get_template("test_disk"))
        assert exc_info.value.status_code == 404

    def test_delete_not_found(self) -> None:
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.delete_template("nonexistent"))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /templates/{name}/validate
# ---------------------------------------------------------------------------


class TestValidateParams:
    def test_valid_params(self) -> None:
        result = asyncio.run(
            tmpl_api.validate_params("test_disk", {"diameter": 100})
        )
        assert result.valid is True
        assert result.errors == []

    def test_invalid_params_out_of_range(self) -> None:
        result = asyncio.run(
            tmpl_api.validate_params("test_disk", {"diameter": 5})
        )
        assert result.valid is False
        assert len(result.errors) > 0

    def test_validate_not_found(self) -> None:
        with pytest.raises(APIError) as exc_info:
            asyncio.run(tmpl_api.validate_params("nonexistent", {}))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# API Key authentication — _require_api_key
# ---------------------------------------------------------------------------


def _make_settings(api_key: str | None = None):
    """Build a mock Settings with the given api_key."""
    from backend.config import Settings

    return Settings(api_key=api_key)


class TestRequireApiKey:
    """Unit tests for the _require_api_key dependency function."""

    def test_no_key_configured_allows_access(self) -> None:
        """When api_key is None (unconfigured), all requests pass."""
        with patch(
            "backend.config.Settings",
            return_value=_make_settings(api_key=None),
        ):
            # Should not raise
            tmpl_api._require_api_key(x_api_key=None)

    def test_correct_key_allows_access(self) -> None:
        """When correct API key is provided, request passes."""
        with patch(
            "backend.config.Settings",
            return_value=_make_settings(api_key="secret-123"),
        ):
            tmpl_api._require_api_key(x_api_key="secret-123")

    def test_missing_key_returns_401(self) -> None:
        """When api_key is configured but header is missing, raise 401."""
        with patch(
            "backend.config.Settings",
            return_value=_make_settings(api_key="secret-123"),
        ):
            with pytest.raises(APIError) as exc_info:
                tmpl_api._require_api_key(x_api_key=None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_wrong_key_returns_401(self) -> None:
        """When api_key is configured but header value is wrong, raise 401."""
        with patch(
            "backend.config.Settings",
            return_value=_make_settings(api_key="secret-123"),
        ):
            with pytest.raises(APIError) as exc_info:
                tmpl_api._require_api_key(x_api_key="wrong-key")
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_get_list_no_auth_required(self) -> None:
        """GET list_templates works without API key (no auth on GET)."""
        result = asyncio.run(tmpl_api.list_templates())
        assert isinstance(result, list)

    def test_get_single_no_auth_required(self) -> None:
        """GET get_template works without API key (no auth on GET)."""
        result = asyncio.run(tmpl_api.get_template("test_disk"))
        assert result["name"] == "test_disk"

    def test_validate_no_auth_required(self) -> None:
        """POST validate_params works without API key (read-only)."""
        result = asyncio.run(
            tmpl_api.validate_params("test_disk", {"diameter": 100})
        )
        assert result.valid is True
