"""Tests for mesh_healer dual-channel node."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_severe_high_non_manifold_ratio(self):
        """大量 non-manifold 边 → diagnosed as severe。"""
        from backend.graph.strategies.heal.diagnose import diagnose

        # 构造含 non-manifold 边的退化 mesh:
        # 多个三角形共享同一条边（> 2 个面共享）
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0],
            [0, 0, 1], [1, 0, 1], [0, 1, 1],
        ], dtype=float)
        # 三个面共享边 (0,1)，制造 non-manifold
        faces = np.array([
            [0, 1, 2],
            [0, 1, 3],
            [0, 1, 4],
        ])
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        result = diagnose(mesh)
        # 非水密 mesh，至少应为 moderate 或 severe
        assert result.level in ("moderate", "severe")
        assert any("non-manifold" in i for i in result.issues)

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
        import tempfile
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


class TestMeshHealerConfig:
    def test_default_values(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig

        cfg = MeshHealerConfig()
        assert cfg.strategy == "algorithm"
        assert cfg.neural_enabled is False
        assert cfg.voxel_resolution == 128
        assert cfg.retopo_threshold == 100000

    def test_inherits_neural_strategy_config(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from backend.graph.configs.neural import NeuralStrategyConfig

        assert issubclass(MeshHealerConfig, NeuralStrategyConfig)

    def test_strategy_literal_rejects_invalid(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MeshHealerConfig(strategy="invalid")

    def test_neural_strategy_requires_endpoint(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MeshHealerConfig(
                strategy="neural",
                neural_enabled=True,
                neural_endpoint=None,
            )

    def test_neural_strategy_requires_neural_enabled(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="neural_enabled"):
            MeshHealerConfig(
                strategy="neural",
                neural_enabled=False,
            )

    def test_auto_strategy_with_neural_enabled_requires_endpoint(self):
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MeshHealerConfig(
                strategy="auto",
                neural_enabled=True,
                neural_endpoint=None,
            )


class TestMeshHealerNode:
    def test_node_registered_with_strategies(self):
        """mesh_healer 注册了 algorithm + neural 两种策略。"""
        from backend.graph.registry import registry
        import backend.graph.discovery as disc

        disc._discovered = False
        disc.discover_nodes()

        desc = registry.get("mesh_healer")
        assert desc is not None
        assert desc.name == "mesh_healer"
        assert "algorithm" in desc.strategies
        assert "neural" in desc.strategies
        assert desc.default_strategy == "algorithm"
        assert desc.fallback_chain == ["algorithm", "neural"]
        assert "raw_mesh" in desc.requires
        assert "watertight_mesh" in desc.produces
        assert desc.input_types == ["organic"]

    def test_config_model_is_mesh_healer_config(self):
        from backend.graph.registry import registry
        from backend.graph.configs.mesh_healer import MeshHealerConfig
        import backend.graph.discovery as disc

        disc._discovered = False
        disc.discover_nodes()

        desc = registry.get("mesh_healer")
        assert desc.config_model is MeshHealerConfig


class TestFallbackIntegration:
    """algorithm 失败 → auto 模式 fallback 到 neural。"""

    @pytest.mark.asyncio
    async def test_auto_fallback_to_neural(self):
        """algorithm 策略 execute 抛异常 → auto 模式 fallback 到 neural。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        class FailAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                raise RuntimeError("algorithm failed")

        class SuccessNeural(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "neural")

        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc = NodeDescriptor(
            name="test_fallback",
            display_name="Fallback Test",
            fn=fallback_node,
            strategies={"algorithm": FailAlgorithm, "neural": SuccessNeural},
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_fallback": {"strategy": "auto"}},
            "node_trace": [],
        }
        result = await wrapped(state)

        # Verify fallback trace
        traces = result.get("node_trace", [])
        assert len(traces) == 1
        entry = traces[0]
        assert entry["node"] == "test_fallback"
        assert "fallback" in entry
        fb = entry["fallback"]
        assert fb["fallback_triggered"] is True
        assert fb["strategy_used"] == "neural"
        assert len(fb["strategies_attempted"]) == 2

    @pytest.mark.asyncio
    async def test_auto_algorithm_success_no_fallback(self):
        """algorithm 策略成功 → fallback_triggered=False。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        class SuccessAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "algorithm")

        class SuccessNeural(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "neural")

        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc = NodeDescriptor(
            name="test_no_fallback",
            display_name="No Fallback Test",
            fn=fallback_node,
            strategies={"algorithm": SuccessAlgorithm, "neural": SuccessNeural},
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_no_fallback": {"strategy": "auto"}},
            "node_trace": [],
        }
        result = await wrapped(state)

        traces = result.get("node_trace", [])
        assert len(traces) == 1
        fb = traces[0]["fallback"]
        assert fb["fallback_triggered"] is False
        assert fb["strategy_used"] == "algorithm"

    @pytest.mark.asyncio
    async def test_auto_neural_disabled_only_tries_algorithm(self):
        """auto 模式 + neural 未配置 → 仅尝试 algorithm，neural 不参与 fallback。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        neural_called = False

        class SuccessAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                ctx.put_data("healed_by", "algorithm")

        class NeuralShouldNotBeCalled(NodeStrategy):
            def check_available(self) -> bool:
                return False

            async def execute(self, ctx):
                nonlocal neural_called
                neural_called = True

        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc = NodeDescriptor(
            name="test_neural_disabled",
            display_name="Neural Disabled Test",
            fn=fallback_node,
            strategies={
                "algorithm": SuccessAlgorithm,
                "neural": NeuralShouldNotBeCalled,
            },
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_neural_disabled": {"strategy": "auto"}},
            "node_trace": [],
        }
        await wrapped(state)
        assert not neural_called

    @pytest.mark.asyncio
    async def test_auto_neural_disabled_algorithm_fails_hard_error(self):
        """auto 模式 + neural disabled + algorithm 失败 → 硬错误（raise）。"""
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy

        class FailAlgorithm(NodeStrategy):
            async def execute(self, ctx):
                raise RuntimeError("all levels exhausted")

        class NeuralDisabled(NodeStrategy):
            def check_available(self) -> bool:
                return False

            async def execute(self, ctx):
                raise AssertionError("should never be called")

        async def fallback_node(ctx):
            await ctx.execute_with_fallback()

        desc = NodeDescriptor(
            name="test_hard_fail",
            display_name="Hard Fail Test",
            fn=fallback_node,
            strategies={
                "algorithm": FailAlgorithm,
                "neural": NeuralDisabled,
            },
            default_strategy="algorithm",
            fallback_chain=["algorithm", "neural"],
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "organic",
            "assets": {}, "data": {},
            "pipeline_config": {"test_hard_fail": {"strategy": "auto"}},
            "node_trace": [],
        }

        # _wrap_node re-raises when non_fatal=False → exception propagates
        with pytest.raises(RuntimeError, match="No strategy succeeded"):
            await wrapped(state)
