"""Shared test fixtures for yt2bili."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yt2bili.core.config import AppConfig
from yt2bili.core.models import Base
from yt2bili.db.repository import Repository


@pytest.fixture()
def app_config() -> AppConfig:
    """Return an AppConfig with all defaults."""
    return AppConfig()


@pytest_asyncio.fixture()
async def db_engine() -> AsyncGenerator[Any, None]:
    """Create an in-memory SQLite engine with tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """Provide a scoped async session for each test."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture()
async def repo(db_session: AsyncSession) -> Repository:
    """Provide a Repository bound to the test session."""
    return Repository(db_session)
