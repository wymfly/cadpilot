"""Tests for pipeline config API endpoints (nodes + validate)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1.pipeline_config import router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_descriptor(**overrides):
    """Create a mock NodeDescriptor."""
    defaults = {
        "name": "test_node",
        "display_name": "Test Node",
        "requires": [],
        "produces": ["test_asset"],
        "input_types": ["text"],
        "strategies": {},
        "default_strategy": None,
        "is_entry": False,
        "is_terminal": False,
        "supports_hitl": False,
        "non_fatal": False,
        "description": "A test node",
        "config_model": None,
    }
    defaults.update(overrides)
    desc = MagicMock()
    for k, v in defaults.items():
        setattr(desc, k, v)
    return desc


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/nodes
# ---------------------------------------------------------------------------


class TestListPipelineNodes:
    @patch("backend.graph.discovery.discover_nodes")
    @patch("backend.graph.registry.registry")
    def test_returns_nodes(self, mock_registry, mock_discover, client):
        desc = _make_descriptor(name="analyze_intent", display_name="意图分析")
        mock_registry.all.return_value = {"analyze_intent": desc}

        resp = client.get("/api/v1/pipeline/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["name"] == "analyze_intent"
        assert data["nodes"][0]["display_name"] == "意图分析"

    @patch("backend.graph.discovery.discover_nodes")
    @patch("backend.graph.registry.registry")
    def test_includes_config_schema(self, mock_registry, mock_discover, client):
        config_model = MagicMock()
        config_model.model_json_schema.return_value = {"type": "object", "properties": {}}
        desc = _make_descriptor(name="gen", config_model=config_model)
        mock_registry.all.return_value = {"gen": desc}

        resp = client.get("/api/v1/pipeline/nodes")
        data = resp.json()
        assert "config_schema" in data["nodes"][0]

    @patch("backend.graph.discovery.discover_nodes")
    @patch("backend.graph.registry.registry")
    def test_empty_registry(self, mock_registry, mock_discover, client):
        mock_registry.all.return_value = {}

        resp = client.get("/api/v1/pipeline/nodes")
        assert resp.status_code == 200
        assert resp.json()["nodes"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/validate
# ---------------------------------------------------------------------------


class TestValidatePipelineConfig:
    @patch("backend.graph.resolver.DependencyResolver.resolve")
    @patch("backend.graph.discovery.discover_nodes")
    def test_valid_config(self, mock_discover, mock_resolve, client):
        mock_resolved = MagicMock()
        mock_resolved.ordered_nodes = [
            _make_descriptor(name="a"),
            _make_descriptor(name="b"),
        ]
        mock_resolved.interrupt_before = ["b"]
        mock_resolve.return_value = mock_resolved

        resp = client.post("/api/v1/pipeline/validate", json={
            "input_type": "text",
            "config": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["node_count"] == 2
        assert data["topology"] == ["a", "b"]
        assert data["interrupt_before"] == ["b"]

    @patch("backend.graph.resolver.DependencyResolver.resolve")
    @patch("backend.graph.discovery.discover_nodes")
    def test_invalid_config(self, mock_discover, mock_resolve, client):
        mock_resolve.side_effect = ValueError("Cycle detected")

        resp = client.post("/api/v1/pipeline/validate", json={
            "input_type": "text",
            "config": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Cycle detected" in data["error"]

    @patch("backend.graph.resolver.DependencyResolver.resolve")
    @patch("backend.graph.discovery.discover_nodes")
    def test_no_input_type(self, mock_discover, mock_resolve, client):
        mock_resolved = MagicMock()
        mock_resolved.ordered_nodes = []
        mock_resolved.interrupt_before = []
        mock_resolve.return_value = mock_resolved

        resp = client.post("/api/v1/pipeline/validate", json={"config": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True


# ---------------------------------------------------------------------------
# Existing endpoints still work
# ---------------------------------------------------------------------------


class TestExistingEndpoints:
    def test_tooltips(self, client):
        resp = client.get("/api/v1/pipeline/tooltips")
        assert resp.status_code == 200
        data = resp.json()
        assert "ocr_assist" in data

    def test_presets(self, client):
        resp = client.get("/api/v1/pipeline/presets")
        assert resp.status_code == 200
        data = resp.json()
        names = [p["name"] for p in data]
        assert "fast" in names
        assert "balanced" in names
