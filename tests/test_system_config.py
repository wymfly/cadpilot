"""Tests for SystemConfigStore."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from backend.graph.system_config import SystemConfigStore


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "system_config.json"
    return SystemConfigStore(path=str(path))


class TestSystemConfigStore:
    def test_load_missing_file_returns_empty(self, store):
        assert store.load() == {}

    def test_save_and_load_roundtrip(self, store):
        data = {"generate_raw_mesh": {"hunyuan3d_api_key": "sk-test123"}}
        store.save(data)
        assert store.load() == data

    def test_get_node_existing(self, store):
        store.save({"generate_raw_mesh": {"key": "val"}})
        assert store.get_node("generate_raw_mesh") == {"key": "val"}

    def test_get_node_missing(self, store):
        store.save({"generate_raw_mesh": {"key": "val"}})
        assert store.get_node("mesh_healer") == {}

    def test_get_node_empty_store(self, store):
        assert store.get_node("anything") == {}

    def test_atomic_write_no_corruption(self, store, tmp_path):
        """Save creates valid JSON even if called repeatedly."""
        for i in range(5):
            store.save({"node": {"key": f"val-{i}"}})
        result = store.load()
        assert result == {"node": {"key": "val-4"}}
        # Verify no temp files left behind
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "system_config.json"


class TestNodeContextMerge:
    """NodeContext.from_state merges system config as defaults."""

    def test_system_config_provides_defaults(self):
        from backend.graph.context import NodeContext
        from backend.graph.descriptor import NodeDescriptor
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig

        async def _noop(**kw):
            pass

        with patch("backend.graph.context.system_config_store") as mock_store:
            mock_store.get_node.return_value = {"hunyuan3d_endpoint": "https://sys.example.com"}

            desc = NodeDescriptor(
                name="generate_raw_mesh",
                display_name="Generate Raw Mesh",
                fn=_noop,
                config_model=GenerateRawMeshConfig,
            )
            state = {"pipeline_config": {}, "assets": {}, "data": {}}
            ctx = NodeContext.from_state(state, desc)
            assert ctx.config.hunyuan3d_endpoint == "https://sys.example.com"

    def test_per_request_overrides_system_config(self):
        from backend.graph.context import NodeContext
        from backend.graph.descriptor import NodeDescriptor
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig

        async def _noop(**kw):
            pass

        with patch("backend.graph.context.system_config_store") as mock_store:
            mock_store.get_node.return_value = {"hunyuan3d_endpoint": "https://sys.example.com"}

            desc = NodeDescriptor(
                name="generate_raw_mesh",
                display_name="Generate Raw Mesh",
                fn=_noop,
                config_model=GenerateRawMeshConfig,
            )
            state = {
                "pipeline_config": {
                    "generate_raw_mesh": {"hunyuan3d_endpoint": "https://override.com"}
                },
                "assets": {}, "data": {},
            }
            ctx = NodeContext.from_state(state, desc)
            assert ctx.config.hunyuan3d_endpoint == "https://override.com"

    def test_no_system_config_unchanged_behavior(self):
        from backend.graph.context import NodeContext
        from backend.graph.descriptor import NodeDescriptor
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig

        async def _noop(**kw):
            pass

        with patch("backend.graph.context.system_config_store") as mock_store:
            mock_store.get_node.return_value = {}

            desc = NodeDescriptor(
                name="generate_raw_mesh",
                display_name="Generate Raw Mesh",
                fn=_noop,
                config_model=GenerateRawMeshConfig,
            )
            state = {"pipeline_config": {}, "assets": {}, "data": {}}
            ctx = NodeContext.from_state(state, desc)
            assert ctx.config.hunyuan3d_endpoint is None  # Pydantic default
