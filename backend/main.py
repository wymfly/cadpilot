"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1.errors import register_error_handlers
from backend.api.v1.router import router as v1_router
from backend.config import Settings
from backend.db.database import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()

    # Pre-discover all node modules (triggers @register_node decorators)
    from backend.graph.discovery import discover_nodes
    discover_nodes()

    # Initialize LangGraph CAD pipeline
    from backend.graph import get_compiled_graph

    app.state.cad_graph = await get_compiled_graph()

    yield

    # Clean up checkpointer resources
    if hasattr(app.state, "cad_graph") and hasattr(app.state.cad_graph, "checkpointer"):
        cp = app.state.cad_graph.checkpointer
        if hasattr(cp, "conn") and cp.conn is not None:
            await cp.conn.close()


app = FastAPI(title="cadpilot", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# V1 统一路由
app.include_router(v1_router, prefix="/api/v1")

# Pipeline asset export (non-versioned — serves LangGraph-managed assets)
from backend.api.routes.export import router as export_router

app.include_router(export_router, prefix="/api")

register_error_handlers(app)

# 旧版路由已全部迁移至 V1，legacy 文件已删除（Phase 5b）

from pathlib import Path as _Path
from starlette.staticfiles import StaticFiles

_outputs_dir = _Path("outputs")
_outputs_dir.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(_outputs_dir)), name="outputs")
