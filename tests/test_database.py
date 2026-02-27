"""Tests for SQLite + SQLAlchemy async database setup."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import Base, async_session, engine, init_db


class _TestModel(Base):
    """Ephemeral model used only in tests."""

    __tablename__ = "test_table"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


@pytest.fixture(autouse=True)
async def _setup_db():
    """Create tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestDatabaseSetup:
    async def test_engine_is_async(self) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)

    async def test_session_factory_yields_async_session(self) -> None:
        async with async_session() as session:
            assert isinstance(session, AsyncSession)

    async def test_init_db_creates_tables(self) -> None:
        # init_db should be idempotent
        await init_db()
        async with async_session() as session:
            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result.fetchall()]
            assert "test_table" in tables

    async def test_crud_roundtrip(self) -> None:
        async with async_session() as session:
            obj = _TestModel(name="hello")
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            assert obj.id is not None
            assert obj.name == "hello"

    async def test_session_expire_on_commit_false(self) -> None:
        """expire_on_commit=False means attributes are still accessible."""
        async with async_session() as session:
            obj = _TestModel(name="persist")
            session.add(obj)
            await session.commit()
            # Should not raise DetachedInstanceError
            assert obj.name == "persist"
