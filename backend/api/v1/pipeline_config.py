"""管道配置端点 — GET /api/v1/pipeline/tooltips, /api/v1/pipeline/presets, /nodes, /validate。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.models.pipeline_config import PRESETS, get_tooltips

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/tooltips")
async def get_pipeline_tooltips() -> dict[str, Any]:
    return {k: v.model_dump() for k, v in get_tooltips().items()}


@router.get("/presets")
async def get_pipeline_presets() -> list[dict[str, Any]]:
    return [{"name": k, **v.model_dump()} for k, v in PRESETS.items()]


@router.get("/nodes")
async def list_pipeline_nodes() -> dict[str, Any]:
    """返回所有注册节点的描述符。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry

    discover_nodes()

    nodes = []
    for name, desc in registry.all().items():
        node_info: dict[str, Any] = {
            "name": desc.name,
            "display_name": desc.display_name,
            "requires": desc.requires,
            "produces": desc.produces,
            "input_types": desc.input_types,
            "strategies": list(desc.strategies.keys()),
            "default_strategy": desc.default_strategy,
            "is_entry": desc.is_entry,
            "is_terminal": desc.is_terminal,
            "supports_hitl": desc.supports_hitl,
            "non_fatal": desc.non_fatal,
            "description": desc.description,
        }
        # Add config JSON schema if available
        if desc.config_model:
            from backend.graph.registry import enhance_config_schema
            node_info["config_schema"] = enhance_config_schema(
                desc.config_model.model_json_schema()
            )
        nodes.append(node_info)
    return {"nodes": nodes}


@router.get("/node-presets")
async def get_node_presets() -> list[dict[str, Any]]:
    """返回节点级预设配置列表。"""
    from backend.graph.presets import PIPELINE_PRESETS

    result = []
    for name, preset in PIPELINE_PRESETS.items():
        meta = preset.get("_meta", {})
        config = {k: v for k, v in preset.items() if k != "_meta"}
        result.append({
            "name": name,
            "display_name": meta.get("display_name", name),
            "description": meta.get("description", ""),
            "config": config,
        })
    return result


@router.post("/validate")
async def validate_pipeline_config(request: Request) -> dict[str, Any]:
    """验证 pipeline 配置的有效性。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry
    from backend.graph.resolver import DependencyResolver

    discover_nodes()

    try:
        body = await request.json()
    except Exception:
        return {"valid": False, "error": "Invalid JSON body"}

    if not isinstance(body, dict):
        return {"valid": False, "error": "Request body must be a JSON object"}

    input_type = body.get("input_type")
    config = body.get("config", {})
    if not isinstance(config, dict):
        return {"valid": False, "error": "config must be a JSON object"}

    try:
        resolved = DependencyResolver.resolve(
            registry, config, input_type, include_disabled=False,
        )
        if not resolved.ordered_nodes:
            return {
                "valid": False,
                "error": "至少需要启用一个节点",
                "node_count": 0,
            }
        return {
            "valid": True,
            "node_count": len(resolved.ordered_nodes),
            "topology": [d.name for d in resolved.ordered_nodes],
            "interrupt_before": resolved.interrupt_before,
        }
    except (ValueError, KeyError, TypeError) as exc:
        return {"valid": False, "error": str(exc)}


@router.get("/strategy-availability")
async def get_strategy_availability() -> dict[str, Any]:
    """返回各节点策略的运行时可用性。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry

    discover_nodes()

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for name, desc in registry.all().items():
        if not desc.strategies:
            continue

        strat_status: dict[str, dict[str, Any]] = {}
        for strat_name, strat_cls in desc.strategies.items():
            try:
                config = desc.config_model() if desc.config_model else None
                instance = strat_cls(config=config)
                available = instance.check_available()
                entry: dict[str, Any] = {"available": available}
                if not available:
                    reason = getattr(instance, "unavailable_reason", "不可用")
                    entry["reason"] = reason
                strat_status[strat_name] = entry
            except Exception as exc:
                strat_status[strat_name] = {
                    "available": False,
                    "reason": str(exc),
                }

        result[name] = strat_status

    return result
