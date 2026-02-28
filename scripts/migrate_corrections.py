"""One-time migration: JSON file corrections → SQLite.

Reads backend/data/corrections/*.json and inserts into the
user_corrections table.

WARNING: This script does NOT deduplicate. Running it multiple times
will create duplicate rows. Ensure it is only run once per dataset.

Usage:
    uv run python -m scripts.migrate_corrections
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

CORRECTIONS_DIR = Path("backend/data/corrections")


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 timestamp string to datetime."""
    return datetime.fromisoformat(ts)


async def migrate() -> int:
    """Migrate JSON corrections to SQLite. Returns count of inserted rows."""
    import backend.db.models  # noqa: F401 — register ORM models
    from backend.db.database import async_session, init_db
    from backend.db.repository import create_correction

    await init_db()

    if not CORRECTIONS_DIR.exists():
        logger.info(f"No corrections directory found at {CORRECTIONS_DIR}")
        return 0

    json_files = list(CORRECTIONS_DIR.glob("*.json"))
    if not json_files:
        logger.info("No JSON correction files found")
        return 0

    total = 0
    async with async_session() as session:
        for json_file in json_files:
            logger.info(f"Processing {json_file.name}...")
            corrections = json.loads(json_file.read_text())
            for c in corrections:
                # Parse timestamp string to datetime
                if "timestamp" in c and isinstance(c["timestamp"], str):
                    c["timestamp"] = _parse_timestamp(c["timestamp"])
                # Skip 'id' if present (auto-generated)
                c.pop("id", None)
                await create_correction(session, **c)
                total += 1
            logger.info(f"  → {len(corrections)} corrections from {json_file.name}")
        await session.commit()

    logger.info(f"Migration complete: {total} corrections inserted")
    return total


if __name__ == "__main__":
    asyncio.run(migrate())
