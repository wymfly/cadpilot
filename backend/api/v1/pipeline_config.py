"""管道配置端点 — GET /api/v1/pipeline/tooltips, /api/v1/pipeline/presets, /nodes, /validate。"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Request, Response

from backend.graph.system_config import system_config_store
from backend.models.pipeline_config import PRESETS, get_tooltips

_MASKED_RE = re.compile(r"^.{0,3}\*{4}.{0,4}$")


def _is_masked(value: str) -> bool:
    """Return True if value matches our masking output format."""
    return value == "****" or bool(_MASKED_RE.match(value))


router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/tooltips")
async def get_pipeline_tooltips(response: Response) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/pipeline/nodes>; rel="successor-version"'
    return {k: v.model_dump() for k, v in get_tooltips().items()}


@router.get("/presets")
async def get_pipeline_presets(response: Response) -> list[dict[str, Any]]:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/pipeline/node-presets>; rel="successor-version"'
    return [{"name": k, **v.model_dump()} for k, v in PRESETS.items()]


@router.get("/nodes")
async def list_pipeline_nodes() -> dict[str, Any]:
    """返回所有注册节点的描述符。"""
    from backend.graph.registry import registry

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
    from backend.graph.registry import registry
    from backend.graph.resolver import DependencyResolver

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
    from backend.graph.registry import registry

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for name, desc in registry.all().items():
        if not desc.strategies:
            continue

        strat_status: dict[str, dict[str, Any]] = {}
        for strat_name, strat_cls in desc.strategies.items():
            try:
                config = desc.config_model.model_construct() if desc.config_model else None
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


@router.get("/system-config-schema")
async def get_system_config_schema() -> dict[str, Any]:
    """返回每个节点的 system scope 字段 schema。"""
    from backend.graph.registry import registry, enhance_config_schema

    result: dict[str, Any] = {}
    for name, desc in registry.all().items():
        if not desc.config_model:
            continue
        schema = enhance_config_schema(desc.config_model.model_json_schema())
        props = schema.get("properties", {})
        system_props = {
            k: v for k, v in props.items()
            if v.get("x-scope") == "system"
        }
        if system_props:
            required = [r for r in schema.get("required", []) if r in system_props]
            node_schema: dict[str, Any] = {"properties": system_props}
            if required:
                node_schema["required"] = required
            result[name] = node_schema
    return result


@router.get("/system-config")
async def get_system_config() -> dict[str, Any]:
    """返回当前系统配置值（x-sensitive 字段做掩码）。"""
    from backend.graph.registry import registry, enhance_config_schema

    raw = system_config_store.load()

    # Build sensitive field set for masking
    sensitive_fields: dict[str, set[str]] = {}
    for name, desc in registry.all().items():
        if not desc.config_model:
            continue
        schema = enhance_config_schema(desc.config_model.model_json_schema())
        s_fields = set()
        for fname, fschema in schema.get("properties", {}).items():
            if fschema.get("x-sensitive"):
                s_fields.add(fname)
        if s_fields:
            sensitive_fields[name] = s_fields

    # Mask sensitive values
    masked: dict[str, Any] = {}
    for node_name, node_config in raw.items():
        masked_node: dict[str, Any] = {}
        s_set = sensitive_fields.get(node_name, set())
        for k, v in node_config.items():
            if k in s_set and isinstance(v, str) and v:
                if len(v) < 12:
                    masked_node[k] = "****"
                else:
                    masked_node[k] = v[:3] + "****" + v[-4:]
            else:
                masked_node[k] = v
        masked[node_name] = masked_node
    return masked


@router.put("/system-config")
async def update_system_config(request: Request) -> Any:
    """保存系统配置（仅接受 system scope 字段，做类型验证）。"""
    from backend.graph.registry import registry, enhance_config_schema

    try:
        body = await request.json()
    except Exception:
        return Response(
            status_code=400,
            content='{"error":"Invalid JSON"}',
            media_type="application/json",
        )

    if not isinstance(body, dict):
        return Response(
            status_code=400,
            content='{"error":"Request body must be a JSON object"}',
            media_type="application/json",
        )

    # Validate node names, config types, and scope — build sensitive lookup
    sensitive_lookup: dict[str, set[str]] = {}
    for node_name, node_config in body.items():
        if not isinstance(node_config, dict):
            return Response(
                status_code=400,
                content=json.dumps({"error": f"Config for '{node_name}' must be a JSON object"}),
                media_type="application/json",
            )
        try:
            desc = registry.get(node_name)
        except KeyError:
            return Response(
                status_code=400,
                content=json.dumps({"error": f"Unknown node: {node_name}"}),
                media_type="application/json",
            )
        if not desc.config_model:
            return Response(
                status_code=400,
                content=json.dumps({"error": f"Node '{node_name}' has no config model"}),
                media_type="application/json",
            )
        schema = enhance_config_schema(desc.config_model.model_json_schema())
        props = schema.get("properties", {})
        # Collect sensitive fields
        s_fields = set()
        for fname, fschema in props.items():
            if fschema.get("x-sensitive"):
                s_fields.add(fname)
        if s_fields:
            sensitive_lookup[node_name] = s_fields
        # Scope check
        for field_name in node_config:
            field_schema = props.get(field_name, {})
            if field_schema.get("x-scope") != "system":
                return Response(
                    status_code=400,
                    content=json.dumps({"error": f"field '{field_name}' is not a system-scope field"}),
                    media_type="application/json",
                )

    # Filter out masked sensitive values BEFORE validation (F1+R2-1 fix)
    clean_body: dict[str, dict[str, Any]] = {}
    for node_name, node_config in body.items():
        s_set = sensitive_lookup.get(node_name, set())
        clean_node: dict[str, Any] = {}
        for field_name, field_value in node_config.items():
            if field_name in s_set and isinstance(field_value, str) and _is_masked(field_value):
                continue
            clean_node[field_name] = field_value
        if clean_node:
            clean_body[node_name] = clean_node

    # Type validation via config_model (runs on clean values only)
    for node_name, node_config in clean_body.items():
        desc = registry.get(node_name)
        try:
            desc.config_model(**node_config)
        except Exception as exc:
            return Response(
                status_code=422,
                content=json.dumps({"error": f"Validation error for '{node_name}': {exc}"}),
                media_type="application/json",
            )

    # Atomic deep merge per node (F2+F5 fix: TOCTOU-safe)
    if clean_body:
        system_config_store.update_nodes(clean_body)
    return {"ok": True}
