"""Async SQLAlchemy engine and session factory for SQLite."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DB_PATH = Path(__file__).parent.parent / "data" / "cad3dify.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    DATABASE_URL,
    connect_args={"timeout": 30},
    pool_pre_ping=True,
    echo=False,
)

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables if they don't exist (checkfirst=True by default).

    Used for development and testing. When Alembic migrations are adopted,
    replace this with ``alembic upgrade head`` in the startup sequence.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for dependency injection."""
    async with async_session() as session:
        yield session
