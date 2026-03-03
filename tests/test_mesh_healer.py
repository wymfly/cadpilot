"""Tests for mesh_healer dual-channel node."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh


class TestMeshDiagnosis:
    """diagnose() 按缺陷严重度分级。"""

    def _make_watertight_box(self) -> trimesh.Trimesh:
        """创建水密立方体用于测试。"""
        return trimesh.primitives.Box().to_mesh()

    def _make_open_mesh(self) -> trimesh.Trimesh:
        """创建有孔洞的非水密 mesh（删除一个面）。"""
        box = trimesh.primitives.Box().to_mesh()
        # 删除最后一个面制造孔洞
        faces = box.faces[:-1]
        return trimesh.Trimesh(vertices=box.vertices, faces=faces)

    def _make_flipped_normals(self) -> trimesh.Trimesh:
        """创建 normals 翻转的 mesh。"""
        box = trimesh.primitives.Box().to_mesh()
        # 翻转所有 face winding
        box.faces = np.fliplr(box.faces)
        return box

    def test_clean_mesh_diagnosed_as_clean(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_watertight_box()
        result = diagnose(mesh)
        assert result.level == "clean"
        assert result.issues == []

    def test_flipped_normals_diagnosed_as_mild(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_flipped_normals()
        result = diagnose(mesh)
        assert result.level in ("mild", "moderate")
        assert len(result.issues) > 0

    def test_open_mesh_diagnosed_as_moderate(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_open_mesh()
        result = diagnose(mesh)
        assert result.level in ("moderate", "severe")
        assert len(result.issues) > 0

    def test_level_is_valid_literal(self):
        from backend.graph.strategies.heal.diagnose import diagnose

        mesh = self._make_watertight_box()
        result = diagnose(mesh)
        assert result.level in ("clean", "mild", "moderate", "severe")


class TestValidateRepair:
    """validate_repair() 检查修复结果。"""

    def test_watertight_mesh_passes(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        mesh = trimesh.primitives.Box().to_mesh()
        assert validate_repair(mesh) is True

    def test_non_watertight_fails(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        box = trimesh.primitives.Box().to_mesh()
        faces = box.faces[:-1]
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=faces)
        assert validate_repair(mesh) is False

    def test_empty_mesh_fails(self):
        from backend.graph.strategies.heal.diagnose import validate_repair

        mesh = trimesh.Trimesh()
        assert validate_repair(mesh) is False


from unittest.mock import patch, MagicMock, AsyncMock


class TestAlgorithmHealStrategy:
    """AlgorithmHealStrategy 升级链测试。"""

    def _make_open_mesh(self) -> trimesh.Trimesh:
        box = trimesh.primitives.Box().to_mesh()
        return trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])

    def _make_mock_ctx(self, mesh: trimesh.Trimesh, *, use_data_path: bool = False) -> MagicMock:
        """创建 mock NodeContext。

        Args:
            use_data_path: If True, simulate upstream contract where raw_mesh
                is in state data (raw_mesh_path) instead of asset registry.
        """
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        mesh.export(tmp.name)
        tmp.close()

        ctx = MagicMock()
        if use_data_path:
            # Simulate upstream: AssetRegistry.get() raises KeyError,
            # path is in state data dict instead.
            ctx.get_asset.side_effect = KeyError("raw_mesh")
            ctx.get_data.return_value = tmp.name
        else:
            ctx.get_asset.return_value = MagicMock(path=tmp.name)
            ctx.get_data.return_value = None
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()
        ctx.dispatch_progress = AsyncMock()
        ctx.job_id = "test-job"
        ctx.node_name = "mesh_healer"
        ctx.config = MagicMock()
        ctx.config.voxel_resolution = 128
        ctx.config.retopo_threshold = 100000
        return ctx

    @pytest.mark.asyncio
    async def test_clean_mesh_passes_through(self):
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = trimesh.primitives.Box().to_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        # Should have called put_asset with watertight_mesh
        ctx.put_asset.assert_called_once()
        call_args = ctx.put_asset.call_args
        assert call_args[0][0] == "watertight_mesh"

    @pytest.mark.asyncio
    async def test_reads_from_data_path_when_no_asset(self):
        """上游写 raw_mesh_path 到 data dict -> strategy 通过桥接读取。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = trimesh.primitives.Box().to_mesh()
        ctx = self._make_mock_ctx(mesh, use_data_path=True)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        ctx.put_asset.assert_called_once()
        ctx.get_data.assert_called_with("raw_mesh_path")

    @pytest.mark.asyncio
    async def test_open_mesh_gets_repaired(self):
        """moderate 级 open mesh — mock level2 用 trimesh 修复替代（pymeshfix 不可用）。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        def _trimesh_fill(mesh_in: trimesh.Trimesh) -> trimesh.Trimesh:
            """使用 trimesh 内置修复代替 pymeshfix。"""
            m = mesh_in.copy()
            trimesh.repair.fix_normals(m)
            trimesh.repair.fix_winding(m)
            trimesh.repair.fill_holes(m)
            return m

        mesh = self._make_open_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        # 直接替换实例方法，避免 MagicMock 的 __name__ 问题
        strategy._level2_pymeshfix = _trimesh_fill
        await strategy.execute(ctx)
        ctx.put_asset.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_progress_events(self):
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        mesh = trimesh.primitives.Box().to_mesh()
        ctx = self._make_mock_ctx(mesh)
        strategy = AlgorithmHealStrategy()
        await strategy.execute(ctx)
        assert ctx.dispatch_progress.await_count >= 2  # 至少: diagnose + repair


class TestEscalationChain:
    """升级链行为：低级失败→升级到高级；工具不可用→跳过。"""

    def _make_mock_ctx(self, mesh_path: str) -> MagicMock:
        ctx = MagicMock()
        ctx.get_asset.return_value = MagicMock(path=mesh_path)
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()
        ctx.dispatch_progress = AsyncMock()
        ctx.job_id = "test-job"
        ctx.node_name = "mesh_healer"
        ctx.config = MagicMock()
        ctx.config.voxel_resolution = 128
        ctx.config.retopo_threshold = 100000
        return ctx

    @pytest.mark.asyncio
    async def test_level2_used_when_level1_insufficient(self):
        """Level 1 修复后仍非水密 → 自动升级到 Level 2。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy

        # 创建一个 normals 翻转的 mesh — diagnose 为 mild，chain 从 level1 开始
        box = trimesh.primitives.Box().to_mesh()
        flipped = trimesh.Trimesh(vertices=box.vertices, faces=np.fliplr(box.faces))

        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        flipped.export(tmp.name)
        tmp.close()

        ctx = self._make_mock_ctx(tmp.name)
        strategy = AlgorithmHealStrategy()

        # Mock level1 to return non-watertight mesh (insufficient repair)
        bad_mesh = trimesh.Trimesh(
            vertices=box.vertices, faces=box.faces[:-1]
        )
        fixed = trimesh.primitives.Box().to_mesh()

        with patch.object(strategy, "_level1_trimesh", return_value=bad_mesh):
            with patch.object(strategy, "_level2_pymeshfix", return_value=fixed) as mock_l2:
                await strategy.execute(ctx)
                mock_l2.assert_called()

    @pytest.mark.asyncio
    async def test_skip_level2_when_pymeshfix_unavailable(self):
        """PyMeshFix import 失败 → 跳过 Level 2，尝试 Level 3。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
        from backend.graph.strategies.heal.diagnose import MeshDiagnosis

        box = trimesh.primitives.Box().to_mesh()
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])
        diag = MeshDiagnosis(level="moderate", issues=["holes"])

        strategy = AlgorithmHealStrategy()
        good_mesh = trimesh.primitives.Box().to_mesh()

        with patch.object(strategy, "_level2_pymeshfix",
                          side_effect=ImportError("pymeshfix not found")):
            with patch.object(strategy, "_level3_meshlib",
                              return_value=good_mesh):
                result = strategy._escalate(mesh, diag)
                assert result.is_watertight

    def test_all_levels_exhausted_raises(self):
        """所有修复级别均失败 → 抛 RuntimeError。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
        from backend.graph.strategies.heal.diagnose import MeshDiagnosis

        box = trimesh.primitives.Box().to_mesh()
        mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1])
        diag = MeshDiagnosis(level="moderate", issues=["holes"])

        strategy = AlgorithmHealStrategy()

        with patch.object(strategy, "_level2_pymeshfix",
                          side_effect=RuntimeError("fail")):
            with patch.object(strategy, "_level3_meshlib",
                              side_effect=RuntimeError("fail")):
                with pytest.raises(RuntimeError, match="All algorithm repair levels exhausted"):
                    strategy._escalate(mesh, diag)

    def test_escalation_chain_order_severe_starts_at_level3(self):
        """severe 直接从 Level 3 开始，不调用 Level 1/2。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
        from backend.graph.strategies.heal.diagnose import MeshDiagnosis

        strategy = AlgorithmHealStrategy()
        good_mesh = trimesh.primitives.Box().to_mesh()

        l1_called = False
        l2_called = False

        def track_l1(mesh):
            nonlocal l1_called
            l1_called = True

        def track_l2(mesh):
            nonlocal l2_called
            l2_called = True

        with patch.object(strategy, "_level1_trimesh", side_effect=track_l1):
            with patch.object(strategy, "_level2_pymeshfix", side_effect=track_l2):
                with patch.object(strategy, "_level3_meshlib", return_value=good_mesh):
                    strategy._escalate(
                        good_mesh,
                        MeshDiagnosis(level="severe", issues=["self-intersection"]),
                    )
        assert not l1_called, "Level 1 should NOT be called for severe"
        assert not l2_called, "Level 2 should NOT be called for severe"

    def test_escalation_chain_order_mild_starts_at_level1(self):
        """mild 从 Level 1 开始。"""
        from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
        from backend.graph.strategies.heal.diagnose import MeshDiagnosis

        strategy = AlgorithmHealStrategy()
        good_mesh = trimesh.primitives.Box().to_mesh()

        l2_called = False

        def track_l2(mesh):
            nonlocal l2_called
            l2_called = True

        with patch.object(strategy, "_level1_trimesh", return_value=good_mesh):
            with patch.object(strategy, "_level2_pymeshfix", side_effect=track_l2):
                strategy._escalate(
                    good_mesh,
                    MeshDiagnosis(level="mild", issues=["inconsistent orientation"]),
                )
        assert not l2_called, "Level 2 should NOT be called when Level 1 succeeds"


class TestNeuralHealStrategy:
    """NeuralHealStrategy HTTP 调用测试。"""

    @pytest.mark.asyncio
    async def test_calls_repair_endpoint(self):
        from backend.graph.strategies.heal.neural import NeuralHealStrategy

        strategy = NeuralHealStrategy(config=MagicMock(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
            neural_timeout=60,
            health_check_path="/health",
        ))

        ctx = MagicMock()
        ctx.get_asset.return_value = MagicMock(path="/tmp/raw.glb")
        ctx.put_asset = MagicMock()
        ctx.dispatch_progress = AsyncMock()

        mock_response = {
            "mesh_uri": "/tmp/repaired.obj",
            "metrics": {"is_watertight": True, "holes_filled": 3},
        }

        with patch.object(strategy, "_post", new_callable=AsyncMock,
                          return_value=mock_response):
            await strategy.execute(ctx)

        ctx.put_asset.assert_called_once_with(
            "watertight_mesh",
            "/tmp/repaired.obj",
            "obj",
            metadata={"is_watertight": True, "holes_filled": 3},
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_data_path(self):
        """get_asset raises KeyError -> falls back to get_data('raw_mesh_path')."""
        from backend.graph.strategies.heal.neural import NeuralHealStrategy

        strategy = NeuralHealStrategy(config=MagicMock(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
            neural_timeout=60,
            health_check_path="/health",
        ))

        ctx = MagicMock()
        ctx.get_asset.side_effect = KeyError("raw_mesh")
        ctx.get_data.return_value = "/tmp/fallback.glb"
        ctx.put_asset = MagicMock()
        ctx.dispatch_progress = AsyncMock()

        mock_response = {
            "mesh_uri": "/tmp/repaired.obj",
            "metrics": {},
        }

        with patch.object(strategy, "_post", new_callable=AsyncMock,
                          return_value=mock_response) as mock_post:
            await strategy.execute(ctx)

        ctx.get_data.assert_called_with("raw_mesh_path")
        mock_post.assert_awaited_once_with("/v1/repair", {
            "mesh_uri": "/tmp/fallback.glb",
        })

    @pytest.mark.asyncio
    async def test_raises_when_no_mesh_available(self):
        """Neither asset nor data path -> raises ValueError."""
        from backend.graph.strategies.heal.neural import NeuralHealStrategy

        strategy = NeuralHealStrategy(config=MagicMock(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        ))

        ctx = MagicMock()
        ctx.get_asset.side_effect = KeyError("raw_mesh")
        ctx.get_data.return_value = None
        ctx.dispatch_progress = AsyncMock()

        with pytest.raises(ValueError, match="No raw mesh found"):
            await strategy.execute(ctx)

    def test_inherits_neural_strategy(self):
        from backend.graph.strategies.heal.neural import NeuralHealStrategy
        from backend.graph.strategies.neural import NeuralStrategy

        assert issubclass(NeuralHealStrategy, NeuralStrategy)
