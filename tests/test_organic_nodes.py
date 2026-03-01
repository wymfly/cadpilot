"""Tests for organic graph nodes (analyze, generate, postprocess)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.graph.nodes.organic import (
    analyze_organic_node,
    generate_organic_mesh_node,
    postprocess_organic_node,
)


@pytest.fixture
def base_state():
    return {
        "job_id": "test-organic-001",
        "input_type": "organic",
        "input_text": "一个小熊雕塑",
        "organic_provider": "auto",
        "organic_quality_mode": "standard",
        "organic_reference_image": None,
        "organic_constraints": None,
        "organic_warnings": [],
        "status": "created",
    }


# ---------------------------------------------------------------------------
# analyze_organic_node
# ---------------------------------------------------------------------------


class TestAnalyzeOrganicNode:
    @pytest.mark.asyncio
    async def test_success(self, base_state):
        mock_spec = {
            "prompt_en": "A small bear sculpture",
            "prompt_original": "一个小熊雕塑",
            "shape_category": "figurine",
            "suggested_bounding_box": [80, 60, 100],
            "final_bounding_box": [80, 60, 100],
            "engineering_cuts": [],
            "quality_mode": "standard",
        }
        with patch("backend.graph.nodes.organic.OrganicSpecBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.build = AsyncMock(return_value=MagicMock(model_dump=lambda: mock_spec))
            result = await analyze_organic_node(base_state)

        assert result["status"] == "awaiting_confirmation"
        assert result["organic_spec"] == mock_spec

    @pytest.mark.asyncio
    async def test_timeout(self, base_state):
        with patch("backend.graph.nodes.organic.OrganicSpecBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.build = AsyncMock(side_effect=asyncio.TimeoutError())
            result = await analyze_organic_node(base_state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_generic_error(self, base_state):
        with patch("backend.graph.nodes.organic.OrganicSpecBuilder") as MockBuilder:
            instance = MockBuilder.return_value
            instance.build = AsyncMock(side_effect=RuntimeError("LLM crash"))
            result = await analyze_organic_node(base_state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "generation_error"


# ---------------------------------------------------------------------------
# generate_organic_mesh_node
# ---------------------------------------------------------------------------


class TestGenerateOrganicMeshNode:
    @pytest.fixture
    def gen_state(self, base_state):
        base_state.update({
            "organic_spec": {
                "prompt_en": "A small bear sculpture",
                "prompt_original": "一个小熊雕塑",
                "shape_category": "figurine",
                "final_bounding_box": [80, 60, 100],
                "engineering_cuts": [],
                "quality_mode": "standard",
            },
            "status": "awaiting_confirmation",
        })
        return base_state

    @pytest.mark.asyncio
    async def test_success(self, gen_state):
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=Path("/tmp/test.glb"))

        with patch("backend.infra.mesh_providers.AutoProvider", return_value=mock_provider), \
             patch("backend.infra.mesh_providers.TripoProvider"), \
             patch("backend.infra.mesh_providers.HunyuanProvider"):
            result = await generate_organic_mesh_node(gen_state)

        assert result["raw_mesh_path"] == "/tmp/test.glb"
        assert result["status"] == "generating"

    @pytest.mark.asyncio
    async def test_idempotent_skip(self, gen_state, tmp_path):
        """If raw_mesh_path already exists, skip generation."""
        existing_mesh = tmp_path / "model.glb"
        existing_mesh.write_bytes(b"fake mesh")
        gen_state["raw_mesh_path"] = str(existing_mesh)

        result = await generate_organic_mesh_node(gen_state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_provider_failure(self, gen_state):
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("backend.infra.mesh_providers.AutoProvider", return_value=mock_provider), \
             patch("backend.infra.mesh_providers.TripoProvider"), \
             patch("backend.infra.mesh_providers.HunyuanProvider"):
            result = await generate_organic_mesh_node(gen_state)

        assert result["status"] == "failed"
        assert "API error" in result["error"]

    @pytest.mark.asyncio
    async def test_tripo_provider_selection(self, gen_state):
        gen_state["organic_provider"] = "tripo3d"
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=Path("/tmp/tripo.glb"))

        with patch("backend.infra.mesh_providers.TripoProvider", return_value=mock_provider), \
             patch("backend.infra.mesh_providers.HunyuanProvider"):
            result = await generate_organic_mesh_node(gen_state)

        assert result["raw_mesh_path"] == "/tmp/tripo.glb"


# ---------------------------------------------------------------------------
# postprocess_organic_node
# ---------------------------------------------------------------------------


class TestPostprocessOrganicNode:
    @pytest.fixture
    def pp_state(self, base_state, tmp_path):
        raw_mesh = tmp_path / "raw.glb"
        raw_mesh.write_bytes(b"fake mesh data")
        base_state.update({
            "raw_mesh_path": str(raw_mesh),
            "organic_spec": {
                "prompt_en": "A bear",
                "prompt_original": "小熊",
                "shape_category": "figurine",
                "final_bounding_box": [80, 60, 100],
                "engineering_cuts": [],
                "quality_mode": "standard",
            },
            "organic_quality_mode": "standard",
            "status": "generating",
        })
        return base_state

    @pytest.mark.asyncio
    async def test_full_success(self, pp_state):
        mock_mesh = MagicMock()
        mock_mesh.export = MagicMock()
        mock_repair_info = MagicMock()
        mock_repair_info.status = "success"
        mock_repair_info.message = "OK"
        mock_stats = MagicMock()
        mock_stats.model_dump.return_value = {
            "vertex_count": 100, "face_count": 200,
            "is_watertight": True, "volume_cm3": 1.0,
        }
        mock_pr = MagicMock()
        mock_pr.model_dump.return_value = {"printable": True, "issues": []}

        with patch("backend.core.mesh_post_processor.MeshPostProcessor") as MockPP, \
             patch("backend.core.printability.PrintabilityChecker") as MockPC:
            MockPP.load_mesh.return_value = mock_mesh
            MockPP.repair_mesh.return_value = (mock_mesh, mock_repair_info)
            MockPP.scale_mesh.return_value = mock_mesh
            MockPP.validate_mesh.return_value = mock_stats
            MockPC.return_value.check.return_value = mock_pr

            result = await postprocess_organic_node(pp_state)

        assert result["status"] == "post_processed"
        assert result["organic_result"]["model_url"] is not None
        assert result["organic_result"]["stl_url"] is not None
        assert result["mesh_stats"] is not None

    @pytest.mark.asyncio
    async def test_missing_raw_mesh_path(self, base_state):
        """No raw_mesh_path → immediate failure."""
        base_state["raw_mesh_path"] = None
        result = await postprocess_organic_node(base_state)
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_threemf_export_failure_adds_warning(self, pp_state):
        """3MF export failure should add warning but not fail the pipeline."""
        mock_mesh = MagicMock()
        call_count = 0

        def _export_side_effect(path, file_type=None):
            nonlocal call_count
            call_count += 1
            if file_type == "3mf":
                raise RuntimeError("3MF not supported")

        mock_mesh.export = MagicMock(side_effect=_export_side_effect)
        mock_repair_info = MagicMock()
        mock_repair_info.status = "success"
        mock_repair_info.message = "OK"
        mock_stats = MagicMock()
        mock_stats.model_dump.return_value = {
            "vertex_count": 100, "face_count": 200,
            "is_watertight": True, "volume_cm3": 1.0,
        }
        mock_pr = MagicMock()
        mock_pr.model_dump.return_value = {"printable": True}

        with patch("backend.core.mesh_post_processor.MeshPostProcessor") as MockPP, \
             patch("backend.core.printability.PrintabilityChecker") as MockPC:
            MockPP.load_mesh.return_value = mock_mesh
            MockPP.repair_mesh.return_value = (mock_mesh, mock_repair_info)
            MockPP.scale_mesh.return_value = mock_mesh
            MockPP.validate_mesh.return_value = mock_stats
            MockPC.return_value.check.return_value = mock_pr

            result = await postprocess_organic_node(pp_state)

        assert result["status"] == "post_processed"
        assert result["organic_result"]["threemf_url"] is None
        assert any("3MF" in w for w in result["organic_warnings"])

    @pytest.mark.asyncio
    async def test_draft_skips_boolean_cuts(self, pp_state):
        """Draft quality mode should skip boolean cuts."""
        pp_state["organic_quality_mode"] = "draft"
        pp_state["organic_spec"]["engineering_cuts"] = [{"type": "hole", "diameter": 10}]

        mock_mesh = MagicMock()
        mock_mesh.export = MagicMock()
        mock_repair_info = MagicMock()
        mock_repair_info.status = "success"
        mock_repair_info.message = "OK"
        mock_stats = MagicMock()
        mock_stats.model_dump.return_value = {
            "vertex_count": 100, "face_count": 200,
            "is_watertight": True, "volume_cm3": 1.0,
        }
        mock_pr = MagicMock()
        mock_pr.model_dump.return_value = {"printable": True}

        with patch("backend.core.mesh_post_processor.MeshPostProcessor") as MockPP, \
             patch("backend.core.printability.PrintabilityChecker") as MockPC:
            MockPP.load_mesh.return_value = mock_mesh
            MockPP.repair_mesh.return_value = (mock_mesh, mock_repair_info)
            MockPP.validate_mesh.return_value = mock_stats
            MockPC.return_value.check.return_value = mock_pr

            result = await postprocess_organic_node(pp_state)

        assert result["status"] == "post_processed"
        # scale_mesh should NOT have been called for boolean cuts
        MockPP.apply_boolean_cuts.assert_not_called()
