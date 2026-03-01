"""Tests for LLM configuration system (model, manager, API)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ── T2.1: Model tests ────────────────────────────────────────────────────


class TestLLMConfigModel:
    def test_default_roles_complete(self) -> None:
        from backend.models.llm_config import DEFAULT_ROLES

        expected = {
            "intent_parser",
            "vision_analyzer",
            "code_generator",
            "refiner_vl",
            "refiner_coder",
            "organic_spec",
        }
        assert set(DEFAULT_ROLES.keys()) == expected

    def test_role_config_fields(self) -> None:
        from backend.models.llm_config import DEFAULT_ROLES

        rc = DEFAULT_ROLES["vision_analyzer"]
        assert rc.role == "vision_analyzer"
        assert rc.display_name == "图纸分析"
        assert rc.group == "precision"
        assert rc.default_model == "qwen-vl"
        assert rc.default_temp == 0.1

    def test_role_config_frozen(self) -> None:
        from backend.models.llm_config import DEFAULT_ROLES

        rc = DEFAULT_ROLES["intent_parser"]
        with pytest.raises(AttributeError):
            rc.default_model = "gpt"  # type: ignore[misc]


# ── T2.2: Manager tests ──────────────────────────────────────────────────


class TestLLMConfigManager:
    def test_get_model_for_role_default(self) -> None:
        from backend.infra.llm_config_manager import (
            get_model_for_role,
            invalidate_cache,
        )

        invalidate_cache()
        # Patch config path to non-existent file -> defaults only
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH",
            Path("/tmp/_nonexistent_llm_config.yaml"),
        ):
            invalidate_cache()
            params = get_model_for_role("vision_analyzer")
        assert params.model_name == "qwen-vl-max"  # qwen-vl maps to qwen-vl-max
        invalidate_cache()

    def test_get_model_for_role_unknown(self) -> None:
        from backend.infra.llm_config_manager import invalidate_cache

        invalidate_cache()
        with pytest.raises(ValueError, match="Unknown LLM role"):
            from backend.infra.llm_config_manager import get_model_for_role

            get_model_for_role("nonexistent_role")
        invalidate_cache()

    def test_yaml_override(self, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import (
            get_model_for_role,
            invalidate_cache,
        )

        config_file = tmp_path / "llm_config.yaml"
        config_file.write_text(
            yaml.dump({"roles": {"intent_parser": "claude"}})
        )
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            params = get_model_for_role("intent_parser")
        assert params.model_name == "claude-opus-4-5-20251101"
        invalidate_cache()

    def test_save_and_load(self, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import (
            get_current_config,
            invalidate_cache,
            save_config,
        )

        config_file = tmp_path / "sub" / "llm_config.yaml"
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            save_config({"code_generator": "gpt"})
            cfg = get_current_config()
        assert cfg["code_generator"]["current_model"] == "gpt"
        # Other roles keep defaults
        assert cfg["vision_analyzer"]["current_model"] == "qwen-vl"
        invalidate_cache()

    def test_save_validates_model_name(self, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import invalidate_cache, save_config

        config_file = tmp_path / "llm_config.yaml"
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            with pytest.raises(ValueError, match="Unknown model type"):
                save_config({"intent_parser": "invalid_model_xyz"})
        invalidate_cache()

    def test_save_validates_role_name(self, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import invalidate_cache, save_config

        config_file = tmp_path / "llm_config.yaml"
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            with pytest.raises(ValueError, match="Unknown LLM role"):
                save_config({"nonexistent_role": "gpt"})
        invalidate_cache()

    def test_get_available_models(self) -> None:
        from backend.infra.llm_config_manager import get_available_models

        models = get_available_models()
        names = [m["name"] for m in models]
        assert "qwen" in names
        assert "claude" in names
        assert all("display_name" in m for m in models)

    def test_get_current_config_structure(self) -> None:
        from backend.infra.llm_config_manager import (
            get_current_config,
            invalidate_cache,
        )

        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH",
            Path("/tmp/_nonexistent_llm_config.yaml"),
        ):
            invalidate_cache()
            cfg = get_current_config()
        assert "intent_parser" in cfg
        role_data = cfg["intent_parser"]
        assert "role" in role_data
        assert "display_name" in role_data
        assert "group" in role_data
        assert "default_model" in role_data
        assert "default_temp" in role_data
        assert "current_model" in role_data
        invalidate_cache()


# ── T2.3: Replacement verification ───────────────────────────────────────


class TestHardcodeReplacements:
    """Verify no remaining hardcoded from_model_name calls in replaced files."""

    def test_analysis_node_uses_role(self) -> None:
        import inspect

        from backend.graph.nodes.analysis import _parse_intent

        source = inspect.getsource(_parse_intent)
        assert "get_model_for_role" in source
        assert 'from_model_name("qwen")' not in source

    def test_organic_spec_builder_uses_role(self) -> None:
        import inspect

        from backend.core.organic_spec_builder import OrganicSpecBuilder

        source = inspect.getsource(OrganicSpecBuilder._call_llm)
        assert "get_model_for_role" in source
        assert 'from_model_name("qwen")' not in source


# ── T2.4: API tests ──────────────────────────────────────────────────────


class TestLLMConfigAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app)

    def test_get_llm_config(self, client) -> None:
        resp = client.get("/api/v1/llm-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert "available_models" in data
        assert "intent_parser" in data["roles"]

    def test_list_available_models(self, client) -> None:
        resp = client.get("/api/v1/llm-config/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        names = [m["name"] for m in data["models"]]
        assert "qwen" in names

    def test_update_llm_config(self, client, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import invalidate_cache

        config_file = tmp_path / "llm_config.yaml"
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            resp = client.put(
                "/api/v1/llm-config",
                json={"roles": {"intent_parser": "claude"}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["roles"]["intent_parser"]["current_model"] == "claude"
        invalidate_cache()

    def test_update_invalid_model_returns_422(self, client, tmp_path: Path) -> None:
        from backend.infra.llm_config_manager import invalidate_cache

        config_file = tmp_path / "llm_config.yaml"
        with patch(
            "backend.infra.llm_config_manager._CONFIG_PATH", config_file
        ):
            invalidate_cache()
            resp = client.put(
                "/api/v1/llm-config",
                json={"roles": {"intent_parser": "nonexistent_xyz"}},
            )
            assert resp.status_code == 422
        invalidate_cache()
