"""LLM configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/llm-config", tags=["llm-config"])


class LLMConfigUpdateRequest(BaseModel):
    """Request body for updating role -> model mappings."""

    roles: dict[str, str]  # role -> model_name


@router.get("")
async def get_llm_config() -> dict:
    """Return all LLM roles with current model assignments + available models."""
    from backend.infra.llm_config_manager import (
        get_available_models,
        get_current_config,
    )

    return {
        "roles": get_current_config(),
        "available_models": get_available_models(),
    }


@router.put("")
async def update_llm_config(body: LLMConfigUpdateRequest) -> dict:
    """Persist role -> model overrides and return updated config."""
    from backend.infra.llm_config_manager import get_current_config, save_config

    try:
        save_config(body.roles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"roles": get_current_config()}


@router.get("/models")
async def list_available_models() -> dict:
    """Return list of all supported MODEL_TYPE values."""
    from backend.infra.llm_config_manager import get_available_models

    return {"models": get_available_models()}
