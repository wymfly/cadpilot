"""Integration tests: shell_node passthrough + boolean_assemble compatibility."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestBooleanAssembleReadsShelled:

    def test_boolean_assemble_requires_shelled_mesh(self):
        """After update, boolean_assemble requires shelled_mesh."""
        from backend.graph.registry import registry
        import backend.graph.nodes.boolean_assemble  # noqa: F401
        desc = registry.get("boolean_assemble")
        assert "shelled_mesh" in desc.requires

    @pytest.mark.asyncio
    async def test_passthrough_no_cuts_reads_shelled(self):
        """Passthrough path reads shelled_mesh (not scaled_mesh)."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = MagicMock()
        ctx.config = MagicMock(strategy="manifold3d")
        ctx.has_asset.side_effect = lambda k: k == "shelled_mesh"
        mock_asset = MagicMock(path="/tmp/shelled.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.get_data.return_value = None  # no organic_spec -> no cuts -> passthrough

        await boolean_assemble_node(ctx)

        ctx.get_asset.assert_called_with("shelled_mesh")
        ctx.put_asset.assert_called_once()
        assert ctx.put_asset.call_args[0][0] == "final_mesh"


class TestShellNodeRegistration:

    def test_shell_node_registered(self):
        """shell_node should be registered with correct requires/produces."""
        from backend.graph.registry import registry
        import backend.graph.nodes.shell_node  # noqa: F401
        desc = registry.get("shell_node")
        assert "scaled_mesh" in desc.requires
        assert "shelled_mesh" in desc.produces
        assert desc.non_fatal is False

    def test_shell_node_before_boolean_assemble(self):
        """shell_node produces what boolean_assemble requires."""
        from backend.graph.registry import registry
        import backend.graph.nodes.shell_node  # noqa: F401
        import backend.graph.nodes.boolean_assemble  # noqa: F401
        shell = registry.get("shell_node")
        boolean = registry.get("boolean_assemble")
        assert "shelled_mesh" in shell.produces
        assert "shelled_mesh" in boolean.requires
