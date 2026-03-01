"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

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
from backend.api.v1.errors import register_error_handlers
from backend.api.v1.router import router as v1_router
from backend.config import Settings
from backend.db.database import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()

    # Initialize LangGraph CAD pipeline
    from backend.db.database import DB_PATH
    from backend.graph import get_compiled_graph

    app.state.cad_graph = await get_compiled_graph(str(DB_PATH))

    yield

    # Clean up checkpointer connection
    ctx = getattr(app.state.cad_graph, "_checkpointer_ctx", None)
    if ctx is not None:
        await ctx.__aexit__(None, None, None)


app = FastAPI(title="cad3dify", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# V1 统一路由
app.include_router(v1_router, prefix="/api/v1")
register_error_handlers(app)

# 旧版路由（保持兼容，后续移除）
# app.include_router(health.router, prefix="/api")  # [V1-MIGRATED]
# app.include_router(pipeline.router, prefix="/api/pipeline")  # [V1-MIGRATED]
app.include_router(generate.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(benchmark.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(standards.router, prefix="/api")
app.include_router(print_config.router, prefix="/api")
# app.include_router(rag.router, prefix="/api")  # [V1-MIGRATED]
app.include_router(organic.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(history.router, prefix="/api")

from pathlib import Path as _Path
from starlette.staticfiles import StaticFiles

_outputs_dir = _Path("outputs")
_outputs_dir.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(_outputs_dir)), name="outputs")
