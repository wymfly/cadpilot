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
            node_info["config_schema"] = desc.config_model.model_json_schema()
        nodes.append(node_info)
    return {"nodes": nodes}


@router.post("/validate")
async def validate_pipeline_config(request: Request) -> dict[str, Any]:
    """验证 pipeline 配置的有效性。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry
    from backend.graph.resolver import DependencyResolver

    discover_nodes()

    body = await request.json()
    input_type = body.get("input_type")
    config = body.get("config", {})

    try:
        resolved = DependencyResolver.resolve(registry, config, input_type)
        return {
            "valid": True,
            "node_count": len(resolved.ordered_nodes),
            "topology": [d.name for d in resolved.ordered_nodes],
            "interrupt_before": resolved.interrupt_before,
        }
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}
