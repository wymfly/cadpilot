"""Tests for the async repository layer (T23).

Covers:
- Job CRUD lifecycle
- OrganicJob CRUD lifecycle
- UserCorrection CRUD
- Pagination and filtering
- JSON field queries
- Persistence across engine dispose/recreate (simulated process restart)

Pre-drafted based on planned API signatures (Tasks 17-19).
All tests skip until backend/db/ modules are implemented.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module-level skip: wait for backend/db/ to exist
# ---------------------------------------------------------------------------

try:
    from backend.db.database import Base  # noqa: F401
    from backend.db.repository import create_job, get_job  # noqa: F401

    _DB_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _DB_AVAILABLE = False

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _DB_AVAILABLE, reason="backend/db/ not yet implemented (T17-T19)"),
]

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures — in-memory SQLite async session for test isolation
# ---------------------------------------------------------------------------
# These fixtures will work once backend/db/ is implemented.
# Expected modules:
#   backend.db.database — Base, engine, async_session, init_db
#   backend.db.models   — JobModel, OrganicJobModel, UserCorrectionModel
#   backend.db.repository — CRUD functions for all models


@pytest.fixture()
async def db_engine():
    """Create an in-memory async SQLite engine for a single test."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_tables(db_engine):
    """Create all ORM tables in the in-memory database."""
    from backend.db.database import Base

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture()
async def session(db_engine, db_tables):
    """Provide an async session bound to the in-memory test database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Job CRUD tests
# ---------------------------------------------------------------------------


class TestJobCRUD:
    """Job model repository CRUD operations."""

    async def test_create_and_get_job(self, session) -> None:
        """Create a job and retrieve it by ID."""
        from backend.db.repository import create_job, get_job

        job = await create_job(session, "test-1", input_type="text", input_text="法兰盘")
        assert job.job_id == "test-1"
        assert job.input_type == "text"

        fetched = await get_job(session, "test-1")
        assert fetched is not None
        assert fetched.job_id == "test-1"

    async def test_get_nonexistent_returns_none(self, session) -> None:
        """Getting a non-existent job returns None."""
        from backend.db.repository import get_job

        result = await get_job(session, "nonexistent")
        assert result is None

    async def test_update_job(self, session) -> None:
        """Update job fields (status, result, etc.)."""
        from backend.db.repository import create_job, get_job, update_job

        await create_job(session, "test-2")
        updated = await update_job(session, "test-2", status="generating")
        assert updated.status == "generating"

        fetched = await get_job(session, "test-2")
        assert fetched is not None
        assert fetched.status == "generating"

    async def test_update_nonexistent_raises(self, session) -> None:
        """Updating a non-existent job raises an error."""
        from backend.db.repository import update_job

        with pytest.raises((KeyError, ValueError)):
            await update_job(session, "nonexistent", status="failed")

    async def test_update_json_fields(self, session) -> None:
        """Update JSON columns (intent, result, drawing_spec, etc.)."""
        from backend.db.repository import create_job, get_job, update_job

        await create_job(session, "json-1")
        await update_job(
            session,
            "json-1",
            intent={"template": "flange", "confidence": 0.95},
            result={"model_url": "/outputs/json-1/model.glb"},
        )

        fetched = await get_job(session, "json-1")
        assert fetched is not None
        assert fetched.intent["template"] == "flange"
        assert fetched.result["model_url"].endswith(".glb")

    async def test_job_status_lifecycle(self, session) -> None:
        """Job status transitions through full lifecycle."""
        from backend.db.repository import create_job, get_job, update_job

        await create_job(session, "lifecycle-1", input_type="text")

        for status in ["intent_parsed", "awaiting_confirmation", "generating", "refining", "completed"]:
            await update_job(session, "lifecycle-1", status=status)
            fetched = await get_job(session, "lifecycle-1")
            assert fetched is not None
            assert fetched.status == status

    async def test_job_created_at_auto_set(self, session) -> None:
        """created_at is automatically populated on creation."""
        from backend.db.repository import create_job

        job = await create_job(session, "ts-1")
        assert job.created_at is not None


# ---------------------------------------------------------------------------
# Job pagination and filtering tests
# ---------------------------------------------------------------------------


class TestJobPagination:
    """list_jobs with pagination, status filter, and input_type filter."""

    async def test_list_empty(self, session) -> None:
        """Empty database returns empty list and total=0."""
        from backend.db.repository import list_jobs

        jobs, total = await list_jobs(session)
        assert jobs == []
        assert total == 0

    async def test_list_pagination(self, session) -> None:
        """Create 25 jobs, verify page 2 with page_size=10."""
        from backend.db.repository import create_job, list_jobs

        for i in range(25):
            await create_job(session, f"page-{i:03d}", input_type="text")
        await session.commit()

        jobs, total = await list_jobs(session, page=2, page_size=10)
        assert len(jobs) == 10
        assert total == 25

    async def test_list_last_page(self, session) -> None:
        """Last page may have fewer items than page_size."""
        from backend.db.repository import create_job, list_jobs

        for i in range(25):
            await create_job(session, f"last-{i:03d}")
        await session.commit()

        jobs, total = await list_jobs(session, page=3, page_size=10)
        assert len(jobs) == 5
        assert total == 25

    async def test_filter_by_status(self, session) -> None:
        """Filter jobs by status."""
        from backend.db.repository import create_job, list_jobs, update_job

        await create_job(session, "s1")
        await create_job(session, "s2")
        await update_job(session, "s1", status="completed")
        await session.commit()

        jobs, total = await list_jobs(session, status="completed")
        assert total == 1
        assert jobs[0].job_id == "s1"

    async def test_filter_by_input_type(self, session) -> None:
        """Filter jobs by input_type (text/drawing)."""
        from backend.db.repository import create_job, list_jobs

        await create_job(session, "t1", input_type="text")
        await create_job(session, "d1", input_type="drawing")
        await session.commit()

        jobs, total = await list_jobs(session, input_type="drawing")
        assert total == 1
        assert jobs[0].job_id == "d1"

    async def test_combined_filter_and_pagination(self, session) -> None:
        """Pagination + status filter together."""
        from backend.db.repository import create_job, list_jobs, update_job

        for i in range(15):
            await create_job(session, f"cf-{i:03d}")
            if i < 12:
                await update_job(session, f"cf-{i:03d}", status="completed")
        await session.commit()

        jobs, total = await list_jobs(session, status="completed", page=2, page_size=10)
        assert total == 12
        assert len(jobs) == 2


# ---------------------------------------------------------------------------
# OrganicJob CRUD tests
# ---------------------------------------------------------------------------


class TestOrganicJobCRUD:
    """OrganicJob model repository CRUD operations."""

    async def test_create_and_get_organic_job(self, session) -> None:
        """Create an organic job and retrieve it."""
        from backend.db.repository import create_organic_job, get_organic_job

        job = await create_organic_job(session, "org-1", prompt="机器人手臂")
        assert job.job_id == "org-1"
        assert job.prompt == "机器人手臂"

        fetched = await get_organic_job(session, "org-1")
        assert fetched is not None

    async def test_update_organic_job(self, session) -> None:
        """Update organic job fields (status, progress, result)."""
        from backend.db.repository import (
            create_organic_job,
            get_organic_job,
            update_organic_job,
        )

        await create_organic_job(session, "org-2", prompt="test")
        await update_organic_job(
            session,
            "org-2",
            status="generating",
            progress=0.5,
            message="Generating mesh...",
        )

        fetched = await get_organic_job(session, "org-2")
        assert fetched is not None
        assert fetched.status == "generating"
        assert fetched.progress == pytest.approx(0.5)

    async def test_list_organic_jobs(self, session) -> None:
        """List organic jobs with pagination."""
        from backend.db.repository import create_organic_job, list_organic_jobs

        for i in range(5):
            await create_organic_job(session, f"org-list-{i}", prompt=f"prompt {i}")
        await session.commit()

        jobs, total = await list_organic_jobs(session, page=1, page_size=3)
        assert len(jobs) == 3
        assert total == 5


# ---------------------------------------------------------------------------
# UserCorrection tests
# ---------------------------------------------------------------------------


class TestUserCorrections:
    """UserCorrection model repository operations."""

    async def test_create_correction(self, session) -> None:
        """Create a user correction record."""
        from backend.db.repository import create_correction

        correction = await create_correction(
            session,
            job_id="corr-1",
            field_path="overall_dimensions.diameter",
            original_value="50.0",
            corrected_value="55.0",
        )
        assert correction.job_id == "corr-1"
        assert correction.field_path == "overall_dimensions.diameter"

    async def test_list_corrections_by_job(self, session) -> None:
        """List corrections filtered by job_id."""
        from backend.db.repository import create_correction, list_corrections_by_job

        await create_correction(
            session,
            job_id="j1",
            field_path="a",
            original_value="1",
            corrected_value="2",
        )
        await create_correction(
            session,
            job_id="j1",
            field_path="b",
            original_value="3",
            corrected_value="4",
        )
        await create_correction(
            session,
            job_id="j2",
            field_path="c",
            original_value="5",
            corrected_value="6",
        )
        await session.commit()

        corrections = await list_corrections_by_job(session, "j1")
        assert len(corrections) == 2


# ---------------------------------------------------------------------------
# Persistence across engine dispose/recreate (process restart simulation)
# ---------------------------------------------------------------------------


class TestPersistence:
    """Verify data survives engine disposal (simulated process restart)."""

    async def test_job_persists_after_engine_dispose(self, tmp_path) -> None:
        """Create job → dispose engine → recreate → data still there."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from backend.db.database import Base
        from backend.db.repository import create_job, get_job

        db_path = tmp_path / "test_persist.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        # Phase 1: Create engine, init DB, insert data
        engine1 = create_async_engine(db_url, connect_args={"timeout": 30})
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)
        async with factory1() as session:
            await create_job(session, "persist-test", input_type="drawing")
            await session.commit()
        await engine1.dispose()

        # Phase 2: Recreate engine + session — data should survive
        engine2 = create_async_engine(db_url, connect_args={"timeout": 30})
        factory2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
        async with factory2() as session:
            fetched = await get_job(session, "persist-test")
            assert fetched is not None
            assert fetched.input_type == "drawing"
        await engine2.dispose()

    async def test_organic_job_persists_after_restart(self, tmp_path) -> None:
        """OrganicJob data also survives engine disposal."""
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from backend.db.database import Base
        from backend.db.repository import create_organic_job, get_organic_job

        db_path = tmp_path / "test_organic_persist.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        engine1 = create_async_engine(db_url, connect_args={"timeout": 30})
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)
        async with factory1() as session:
            await create_organic_job(session, "org-persist", prompt="手臂")
            await session.commit()
        await engine1.dispose()

        engine2 = create_async_engine(db_url, connect_args={"timeout": 30})
        factory2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
        async with factory2() as session:
            fetched = await get_organic_job(session, "org-persist")
            assert fetched is not None
            assert fetched.prompt == "手臂"
        await engine2.dispose()
