"""Database engine and async session factory."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from yt2bili.core.models import Base


def _ensure_sqlite_dir(database_url: str) -> str:
    """Ensure the parent directory for a SQLite file URL exists.

    Handles both absolute paths and ``~``-prefixed paths.
    For non-SQLite URLs or in-memory databases the URL is returned unchanged.
    """
    match = re.match(r"^(sqlite(?:\+\w+)?:///)(~?.+)$", database_url)
    if match is None:
        return database_url
    prefix, raw_path = match.group(1), match.group(2)
    expanded = Path(raw_path).expanduser().resolve()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{expanded}"


async def create_engine(database_url: str) -> AsyncEngine:
    """Create and return an async SQLAlchemy engine.

    For SQLite file URLs the parent directory is created automatically
    so that the database file can be opened.
    Also creates all tables if they do not exist.
    """
    resolved_url = _ensure_sqlite_dir(database_url)
    engine = create_async_engine(resolved_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
