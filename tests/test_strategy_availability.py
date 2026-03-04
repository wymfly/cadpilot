"""Tests for GET /api/v1/pipeline/strategy-availability endpoint."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.graph.descriptor import NodeDescriptor, NodeStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy_cls(*, available: bool = True, reason: str = "") -> type[NodeStrategy]:
    """Create a concrete NodeStrategy subclass with controllable availability."""

    class _Strat(NodeStrategy):
        async def execute(self, ctx: Any) -> Any:
            pass

        def check_available(self) -> bool:
            if not available:
                self.unavailable_reason = reason
            return available

    return _Strat


def _make_failing_strategy_cls(error_msg: str) -> type[NodeStrategy]:
    """Strategy whose __init__ raises an exception."""

    class _FailStrat(NodeStrategy):
        def __init__(self, config=None):
            raise RuntimeError(error_msg)

        async def execute(self, ctx: Any) -> Any:
            pass

    return _FailStrat


def _make_descriptor(
    name: str,
    strategies: dict[str, type[NodeStrategy]] | None = None,
    config_model: Any = None,
) -> NodeDescriptor:
    async def _noop(ctx: Any) -> None:
        pass

    return NodeDescriptor(
        name=name,
        display_name=name,
        fn=_noop,
        strategies=strategies or {},
        config_model=config_model,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from backend.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStrategyAvailability:
    """GET /api/v1/pipeline/strategy-availability"""

    def test_endpoint_returns_200(self, client: TestClient) -> None:
        """Smoke test: endpoint returns 200 with dict response."""
        mock_registry = MagicMock()
        mock_registry.all.return_value = {}

        with (
            patch("backend.graph.discovery.discover_nodes"),
            patch("backend.graph.registry.registry", mock_registry),
        ):
            resp = client.get("/api/v1/pipeline/strategy-availability")

        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_response_format(self, client: TestClient) -> None:
        """Response structure: {node: {strategy: {available: bool}}}."""
        strat_cls = _make_strategy_cls(available=True)
        desc = _make_descriptor("gen_node", strategies={"fast": strat_cls})

        mock_registry = MagicMock()
        mock_registry.all.return_value = {"gen_node": desc}

        with (
            patch("backend.graph.discovery.discover_nodes"),
            patch("backend.graph.registry.registry", mock_registry),
        ):
            resp = client.get("/api/v1/pipeline/strategy-availability")

        data = resp.json()
        assert "gen_node" in data
        assert "fast" in data["gen_node"]
        assert data["gen_node"]["fast"]["available"] is True
        assert "reason" not in data["gen_node"]["fast"]

    def test_unavailable_with_reason(self, client: TestClient) -> None:
        """Unavailable strategy includes reason string."""
        strat_cls = _make_strategy_cls(available=False, reason="缺少 API Key")
        desc = _make_descriptor("mesh_node", strategies={"gpu": strat_cls})

        mock_registry = MagicMock()
        mock_registry.all.return_value = {"mesh_node": desc}

        with (
            patch("backend.graph.discovery.discover_nodes"),
            patch("backend.graph.registry.registry", mock_registry),
        ):
            resp = client.get("/api/v1/pipeline/strategy-availability")

        data = resp.json()
        assert data["mesh_node"]["gpu"]["available"] is False
        assert data["mesh_node"]["gpu"]["reason"] == "缺少 API Key"

    def test_instantiation_error(self, client: TestClient) -> None:
        """Strategy __init__ exception → available=False + reason=error msg."""
        strat_cls = _make_failing_strategy_cls("GPU 不可用")
        desc = _make_descriptor("fail_node", strategies={"broken": strat_cls})

        mock_registry = MagicMock()
        mock_registry.all.return_value = {"fail_node": desc}

        with (
            patch("backend.graph.discovery.discover_nodes"),
            patch("backend.graph.registry.registry", mock_registry),
        ):
            resp = client.get("/api/v1/pipeline/strategy-availability")

        data = resp.json()
        assert data["fail_node"]["broken"]["available"] is False
        assert "GPU 不可用" in data["fail_node"]["broken"]["reason"]

    def test_nodes_without_strategies_excluded(self, client: TestClient) -> None:
        """Nodes with empty strategies dict are not in the response."""
        desc_with = _make_descriptor(
            "with_strats", strategies={"s1": _make_strategy_cls()}
        )
        desc_without = _make_descriptor("no_strats", strategies={})

        mock_registry = MagicMock()
        mock_registry.all.return_value = {
            "with_strats": desc_with,
            "no_strats": desc_without,
        }

        with (
            patch("backend.graph.discovery.discover_nodes"),
            patch("backend.graph.registry.registry", mock_registry),
        ):
            resp = client.get("/api/v1/pipeline/strategy-availability")

        data = resp.json()
        assert "with_strats" in data
        assert "no_strats" not in data
