from __future__ import annotations

import tempfile
from collections.abc import Callable
from string import Template

from loguru import logger

from ..core.api_whitelist import get_whitelist_prompt_section
from ..core.ast_checker import ast_pre_check
from ..core.candidate_scorer import score_candidate, select_best
from ..core.code_generator import CodeGeneratorChain
from ..core.drawing_analyzer import DrawingAnalyzerChain
from ..core.modeling_strategist import ModelingStrategist
from ..core.rollback import RollbackTracker
from ..core.smart_refiner import SmartRefiner
from ..core.validators import (
    compare_topology,
    count_topology,
    cross_section_analysis,
    validate_bounding_box,
    validate_step_geometry,
)
from ..knowledge.part_types import DrawingSpec
from ..infra.agents import execute_python_code
from ..infra.chat_models import MODEL_TYPE
from ..infra.image import ImageData
from ..infra.render import render_and_export_image, render_multi_view
from ..models.pipeline_config import PRESETS, PipelineConfig
from ..v1.cad_code_generator import CadCodeGeneratorChain
from ..v1.cad_code_refiner import CadCodeRefinerChain


def index_map(index: int) -> str:
    if index == 0:
        return "1st"
    elif index == 1:
        return "2nd"
    elif index == 2:
        return "3rd"
    else:
        return f"{index + 1}th"


def generate_step_from_2d_cad_image(
    image_filepath: str,
    output_filepath: str,
    num_refinements: int = 3,
    model_type: MODEL_TYPE = "gpt",
):
    """Generate a STEP file from a 2D CAD image

    Args:
        image_filepath (str): Path to the 2D CAD image
        output_filepath (str): Path to the output STEP file
    """
    only_execute = (model_type == "llama")  # llamaだとagentがうまく動かない
    image_data = ImageData.load_from_file(image_filepath)
    chain = CadCodeGeneratorChain(model_type=model_type)

    result = chain.invoke(image_data)["result"]
    code = Template(result).safe_substitute(output_filename=output_filepath)
    logger.info("1st code generation complete. Running code...")
    logger.debug("Generated 1st code:")
    logger.debug(code)
    output = execute_python_code(code, model_type=model_type, only_execute=only_execute)
    logger.debug(output)

    refiner_chain = CadCodeRefinerChain(model_type=model_type)

    for i in range(num_refinements):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            render_and_export_image(output_filepath, f.name)
            logger.info(f"Temporarily rendered image to {f.name}")
            rendered_image = ImageData.load_from_file(f.name)
            result = refiner_chain.invoke(
                {"code": code, "original_input": image_data, "rendered_result": rendered_image}
            )["result"]
            if result is None:
                logger.error(f"Refinement failed. Skipping to the next step.")
                continue
            code = Template(result).safe_substitute(output_filename=output_filepath)
            logger.info("Refined code generation complete. Running code...")
            logger.debug(f"Generated {index_map(i)} refined code:")
            logger.debug(code)
            try:
                output = execute_python_code(code, model_type=model_type, only_execute=only_execute)
                logger.debug(output)
            except Exception as e:
                logger.error(f"Error occurred during code execution: {e}")
                continue


def _score_geometry(
    output_filepath: str,
    spec: DrawingSpec,
    config: PipelineConfig,
) -> tuple[bool, bool, bool, bool]:
    """Score geometry checks for a candidate: (compiled, volume_ok, bbox_ok, topology_ok)."""
    geo = validate_step_geometry(output_filepath)
    compiled = geo.is_valid
    volume_ok = False
    bbox_ok = False
    topology_ok = False

    if compiled and config.volume_check:
        volume_ok = geo.volume > 0

    if compiled and geo.bbox:
        bbox_result = validate_bounding_box(geo.bbox, spec.overall_dimensions)
        bbox_ok = bbox_result.passed

    if compiled and config.topology_check:
        try:
            topo = count_topology(output_filepath)
            if not topo.error:
                expected_holes = 0
                for feat in spec.features:
                    if feat.type == "hole_pattern":
                        feat_data = feat.spec if isinstance(feat.spec, dict) else feat.spec.model_dump()
                        expected_holes += int(feat_data.get("count", 0))
                if spec.base_body.bore is not None:
                    expected_holes += 1
                topo_cmp = compare_topology(topo, expected_holes=expected_holes)
                topology_ok = topo_cmp.passed
        except Exception:
            pass

    return compiled, volume_ok, bbox_ok, topology_ok


def generate_step_v2(
    image_filepath: str,
    output_filepath: str,
    num_refinements: int | None = None,
    on_spec_ready: Callable | None = None,
    on_progress: Callable | None = None,
    config: PipelineConfig | None = None,
):
    """V2 增强管道：VL 读图 → 策略选择 → Coder 写码 → 智能改进

    Args:
        image_filepath: 输入图片路径
        output_filepath: 输出 STEP 文件路径
        num_refinements: 改进轮数，显式传入时优先于 config；None 则使用 config 值
        on_spec_ready: DrawingSpec 就绪回调 on_spec_ready(spec, reasoning=None)
        on_progress: 进度回调 on_progress(stage: str, data: dict)
            stage="geometry": data={"is_valid", "volume", "bbox", "error"}
            stage="refinement_round": data={"round", "total", "status"}
            stage="candidate": data={"index", "total", "score"}
        config: 管道配置，None 则使用 balanced 预设
    """
    if config is None:
        config = PRESETS["balanced"]

    # 显式传入 num_refinements 优先，否则使用 config 预设值
    effective_refinements = num_refinements if num_refinements is not None else config.max_refinements

    image_data = ImageData.load_from_file(image_filepath)

    # ================================================================
    # 阶段 1: VL 分析图纸
    # ================================================================
    logger.info("[V2] Stage 1: Analyzing drawing with VL model...")
    analyzer = DrawingAnalyzerChain()
    analyzer_result = analyzer.invoke(image_data)
    spec = analyzer_result["result"]
    reasoning = analyzer_result.get("reasoning")

    if spec is None:
        logger.error("[V2] Drawing analysis failed, falling back to v1 pipeline")
        return generate_step_from_2d_cad_image(
            image_filepath, output_filepath, num_refinements, model_type="qwen"
        )

    logger.info(f"[V2] Drawing spec: {spec.part_type}, dims={spec.overall_dimensions}")

    if on_spec_ready:
        try:
            on_spec_ready(spec, reasoning)
        except TypeError:
            on_spec_ready(spec)  # backward compat: old callers accept only (spec,)

    # ================================================================
    # 阶段 1.5: 选择建模策略
    # ================================================================
    logger.info("[V2] Stage 1.5: Selecting modeling strategy...")
    strategist = ModelingStrategist()
    context = strategist.select(spec)
    logger.info(f"[V2] Strategy selected for {spec.part_type}, {len(context.examples)} examples")

    # ---- API 白名单注入（Stage 2 增强） ----
    if config.api_whitelist:
        whitelist_section = get_whitelist_prompt_section()
        context.strategy = context.strategy + "\n\n" + whitelist_section
        logger.info("[V2] API whitelist injected into modeling strategy")

    # ================================================================
    # 阶段 2: Coder 生成代码（支持 Best-of-N）
    # ================================================================
    generator = CodeGeneratorChain()

    if config.best_of_n > 1:
        # ---- Best-of-N 多路生成 ----
        logger.info(
            f"[V2] Stage 2: Best-of-N generation (N={config.best_of_n})..."
        )
        candidates: list[dict] = []

        for candidate_idx in range(config.best_of_n):
            logger.info(
                f"[V2] Candidate {candidate_idx + 1}/{config.best_of_n}: generating..."
            )
            try:
                gen_result = generator.invoke(context)["result"]
            except Exception as e:
                logger.error(f"[V2] Candidate {candidate_idx + 1}: generation failed — {e}")
                continue

            if gen_result is None:
                logger.warning(f"[V2] Candidate {candidate_idx + 1}: no code returned")
                continue

            candidate_code = Template(gen_result).safe_substitute(
                output_filename=output_filepath
            )

            # AST 预检
            if config.ast_pre_check:
                ast_result = ast_pre_check(candidate_code)
                if not ast_result.passed:
                    logger.warning(
                        f"[V2] Candidate {candidate_idx + 1}: AST pre-check failed — "
                        f"{ast_result.errors}"
                    )
                    candidates.append({
                        "code": candidate_code,
                        "score": 0,
                        "index": candidate_idx,
                    })
                    if on_progress:
                        on_progress("candidate", {
                            "index": candidate_idx + 1,
                            "total": config.best_of_n,
                            "score": 0,
                        })
                    continue

            # 执行代码
            try:
                exec_output = execute_python_code(
                    candidate_code, model_type="qwen-coder", only_execute=False
                )
                logger.debug(exec_output)
            except Exception as e:
                logger.error(
                    f"[V2] Candidate {candidate_idx + 1}: execution failed — {e}"
                )
                candidates.append({
                    "code": candidate_code,
                    "score": 0,
                    "index": candidate_idx,
                })
                if on_progress:
                    on_progress("candidate", {
                        "index": candidate_idx + 1,
                        "total": config.best_of_n,
                        "score": 0,
                    })
                continue

            # 几何评分
            compiled, volume_ok, bbox_ok, topology_ok = _score_geometry(
                output_filepath, spec, config
            )
            cand_score = score_candidate(
                compiled=compiled,
                volume_ok=volume_ok,
                bbox_ok=bbox_ok,
                topology_ok=topology_ok,
            )
            logger.info(
                f"[V2] Candidate {candidate_idx + 1}: score={cand_score} "
                f"(compiled={compiled}, vol={volume_ok}, bbox={bbox_ok}, topo={topology_ok})"
            )
            candidates.append({
                "code": candidate_code,
                "score": cand_score,
                "index": candidate_idx,
            })
            if on_progress:
                on_progress("candidate", {
                    "index": candidate_idx + 1,
                    "total": config.best_of_n,
                    "score": cand_score,
                })

        # 选最优
        best = select_best(candidates)
        if best is None or best["score"] == 0:
            logger.error("[V2] All candidates failed, aborting")
            return

        code = best["code"]
        logger.info(
            f"[V2] Best candidate: #{best['index'] + 1} with score={best['score']}"
        )

        # 重新执行最优候选（确保 STEP 文件是该候选的输出）
        if len(candidates) > 1:
            try:
                execute_python_code(code, model_type="qwen-coder", only_execute=False)
            except Exception as e:
                logger.error(f"[V2] Re-execution of best candidate failed: {e}")
                return

    else:
        # ---- 单路生成 ----
        logger.info("[V2] Stage 2: Generating CadQuery code with Coder model...")
        result = generator.invoke(context)["result"]

        if result is None:
            logger.error("[V2] Code generation failed")
            return

        code = Template(result).safe_substitute(output_filename=output_filepath)
        logger.info("[V2] Code generation complete.")
        logger.debug(f"Generated code:\n{code}")

        # AST 预检（单路模式）
        if config.ast_pre_check:
            ast_result = ast_pre_check(code)
            if not ast_result.passed:
                logger.error(f"[V2] AST pre-check failed: {ast_result.errors}")
                # 不阻断——仍尝试执行，因为 AST 检查可能误报
                for w in ast_result.warnings:
                    logger.warning(f"[V2] AST warning: {w}")

        # 阶段 3: 执行代码
        logger.info("[V2] Executing generated code...")
        output = execute_python_code(code, model_type="qwen-coder", only_execute=False)
        logger.debug(output)

    # ================================================================
    # 阶段 3.5: 几何验证
    # ================================================================
    geo = validate_step_geometry(output_filepath)
    if geo.is_valid:
        logger.info(
            f"[V2] Geometry valid — volume={geo.volume:.1f}, bbox={geo.bbox}"
        )
    else:
        logger.error(f"[V2] Generated geometry invalid: {geo.error}")

    if on_progress:
        on_progress("geometry", {
            "is_valid": geo.is_valid,
            "volume": geo.volume,
            "bbox": geo.bbox,
            "error": geo.error,
        })

    # ================================================================
    # 阶段 4: 智能改进（带 rollback + 多视角 + 结构化反馈 + 拓扑）
    # ================================================================
    refiner = SmartRefiner()

    # 初始化 rollback tracker
    rollback_tracker: RollbackTracker | None = None
    if config.rollback_on_degrade:
        rollback_tracker = RollbackTracker()
        # 计算初始分数
        compiled, volume_ok, bbox_ok, topology_ok = _score_geometry(
            output_filepath, spec, config
        )
        initial_score = score_candidate(
            compiled=compiled,
            volume_ok=volume_ok,
            bbox_ok=bbox_ok,
            topology_ok=topology_ok,
        )
        rollback_tracker.save(code, float(initial_score))
        logger.info(f"[V2] Rollback tracker initialized with score={initial_score}")

    for i in range(effective_refinements):
        logger.info(f"[V2] Stage 4: Smart refinement round {i+1}/{effective_refinements}...")

        # ---- 渲染（单视角或多视角） ----
        rendered_image: ImageData | None = None
        rendered_images: dict[str, ImageData] | None = None

        if config.multi_view_render:
            # 多视角渲染
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    view_paths = render_multi_view(output_filepath, tmpdir)
                    rendered_images = {}
                    for view_name, view_path in view_paths.items():
                        rendered_images[view_name] = ImageData.load_from_file(view_path)
                    # 使用 isometric 视角作为主渲染图
                    if "isometric" in rendered_images:
                        rendered_image = rendered_images["isometric"]
                    elif rendered_images:
                        rendered_image = next(iter(rendered_images.values()))
                    else:
                        logger.error("[V2] No multi-view images rendered")
                        continue
                    logger.info(
                        f"[V2] Multi-view rendered: {list(rendered_images.keys())}"
                    )
            except Exception as e:
                logger.error(f"[V2] Multi-view rendering failed: {e}")
                # 降级到单视角
                rendered_images = None
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    try:
                        render_and_export_image(output_filepath, f.name)
                        rendered_image = ImageData.load_from_file(f.name)
                    except Exception as e2:
                        logger.error(f"[V2] Single-view fallback also failed: {e2}")
                        continue
        else:
            # 单视角渲染
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                try:
                    render_and_export_image(output_filepath, f.name)
                except Exception as e:
                    logger.error(f"[V2] Rendering failed: {e}")
                    continue
                rendered_image = ImageData.load_from_file(f.name)

        # ---- 调用 SmartRefiner ----
        refined_code = refiner.refine(
            code=code,
            original_image=image_data,
            rendered_image=rendered_image,
            drawing_spec=spec,
            step_filepath=output_filepath,
            structured_feedback=config.structured_feedback,
            topology_check=config.topology_check,
        )

        if refined_code is None:
            logger.info(f"[V2] Refinement round {i+1}: PASS — no changes needed")
            if on_progress:
                on_progress("refinement_round", {
                    "round": i + 1, "total": effective_refinements, "status": "PASS",
                })
            break

        new_code = Template(refined_code).safe_substitute(output_filename=output_filepath)
        logger.info(f"[V2] Refinement round {i+1}: applying fixes...")
        logger.debug(f"Refined code:\n{new_code}")

        try:
            output = execute_python_code(new_code, model_type="qwen-coder", only_execute=False)
            logger.debug(output)
        except Exception as e:
            logger.error(f"[V2] Execution failed after refinement: {e}")
            if on_progress:
                on_progress("refinement_round", {
                    "round": i + 1, "total": effective_refinements, "status": "error",
                })
            continue

        # ---- Rollback 检查 ----
        if rollback_tracker is not None:
            compiled, volume_ok, bbox_ok, topology_ok = _score_geometry(
                output_filepath, spec, config
            )
            new_score = float(score_candidate(
                compiled=compiled,
                volume_ok=volume_ok,
                bbox_ok=bbox_ok,
                topology_ok=topology_ok,
            ))
            should_rollback, prev_code = rollback_tracker.check_and_update(
                new_code, new_score
            )
            if should_rollback and prev_code is not None:
                logger.warning(
                    f"[V2] Refinement round {i+1}: ROLLBACK — score degraded"
                )
                code = prev_code
                # 重新执行回滚代码以恢复 STEP 文件
                try:
                    execute_python_code(code, model_type="qwen-coder", only_execute=False)
                except Exception as e:
                    logger.error(f"[V2] Rollback re-execution failed: {e}")
                if on_progress:
                    on_progress("refinement_round", {
                        "round": i + 1,
                        "total": effective_refinements,
                        "status": "rollback",
                    })
                continue
        # ---- 接受新代码 ----
        code = new_code

        if on_progress:
            on_progress("refinement_round", {
                "round": i + 1, "total": effective_refinements, "status": "refined",
            })

    # ================================================================
    # 阶段 5: 后置检查
    # ================================================================

    # 截面分析（post-refinement）
    if config.cross_section_check:
        logger.info("[V2] Stage 5: Running cross-section analysis...")
        try:
            cs_result = cross_section_analysis(output_filepath, spec)
            if cs_result.error:
                logger.warning(f"[V2] Cross-section error: {cs_result.error}")
            else:
                all_ok = all(s.within_tolerance for s in cs_result.sections)
                logger.info(
                    f"[V2] Cross-section analysis: {len(cs_result.sections)} layers, "
                    f"all_ok={all_ok}"
                )
                if not all_ok:
                    for s in cs_result.sections:
                        if not s.within_tolerance:
                            logger.warning(
                                f"[V2] Section at z={s.height:.1f}: "
                                f"expected d={s.expected_diameter:.1f}, "
                                f"measured d={s.measured_diameter:.1f} "
                                f"(deviation={s.deviation_pct:.1f}%)"
                            )
                if on_progress:
                    on_progress("cross_section", {
                        "sections": len(cs_result.sections),
                        "all_ok": all_ok,
                    })
        except Exception as e:
            logger.warning(f"[V2] Cross-section analysis failed: {e}")

    logger.info(f"[V2] Pipeline complete. Output: {output_filepath}")
