"""FastAPI application entry point."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    benchmark,
    export,
    generate,
    health,
    history,
    organic,
    pipeline,
    preview,
    print_config,
    rag,
    standards,
    templates,
)
from backend.config import Settings

settings = Settings()

app = FastAPI(title="cad3dify", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api/pipeline")
app.include_router(generate.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(benchmark.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(standards.router, prefix="/api")
app.include_router(print_config.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(organic.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(history.router, prefix="/api")

from pathlib import Path as _Path
from starlette.staticfiles import StaticFiles

_outputs_dir = _Path("outputs")
_outputs_dir.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(_outputs_dir)), name="outputs")
