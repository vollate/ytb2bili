"""Tests for the avatar caching service."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yt2bili.core.config import AppConfig
from yt2bili.services.avatar import AvatarService

CHANNEL_ID = "UCxxxxxxxxxxxx"


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig()


@pytest.fixture()
def service(config: AppConfig, tmp_path: Path) -> AvatarService:
    svc = AvatarService(config)
    svc._avatar_dir = tmp_path / "avatars"
    return svc


# ── cache hit ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_avatar_cache_hit(service: AvatarService, tmp_path: Path) -> None:
    """When a fresh cached file exists, ``get_avatar`` returns it without fetching."""
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(parents=True)
    cached_file = avatar_dir / f"{CHANNEL_ID}.jpg"
    cached_file.write_bytes(b"\xff\xd8fake-jpeg")

    result = await service.get_avatar(CHANNEL_ID)

    assert result is not None
    assert result == cached_file


# ── cache miss (mock fetch) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_avatar_cache_miss_fetches(service: AvatarService, tmp_path: Path) -> None:
    """On cache miss, ``get_avatar`` delegates to ``fetch_avatar``."""
    expected_path = tmp_path / "avatars" / f"{CHANNEL_ID}.jpg"

    async def _fake_fetch(channel_id: str) -> Path | None:
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        expected_path.write_bytes(b"\xff\xd8fake")
        return expected_path

    service.fetch_avatar = AsyncMock(side_effect=_fake_fetch)  # type: ignore[method-assign]

    result = await service.get_avatar(CHANNEL_ID)

    assert result == expected_path
    service.fetch_avatar.assert_awaited_once_with(CHANNEL_ID)


# ── stale cache triggers refresh ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_cache_triggers_refresh(service: AvatarService, tmp_path: Path) -> None:
    """A cached file older than 7 days should trigger a re-fetch."""
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(parents=True)
    cached_file = avatar_dir / f"{CHANNEL_ID}.jpg"
    cached_file.write_bytes(b"old-data")

    # Backdate mtime by 8 days
    old_mtime = time.time() - 8 * 86_400
    import os

    os.utime(cached_file, (old_mtime, old_mtime))

    async def _fake_fetch(channel_id: str) -> Path | None:
        cached_file.write_bytes(b"new-data")
        return cached_file

    service.fetch_avatar = AsyncMock(side_effect=_fake_fetch)  # type: ignore[method-assign]

    result = await service.get_avatar(CHANNEL_ID)

    assert result == cached_file
    service.fetch_avatar.assert_awaited_once_with(CHANNEL_ID)
    assert cached_file.read_bytes() == b"new-data"


# ── fetch failure returns None ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_failure_returns_none(service: AvatarService) -> None:
    """If both RSS and HTML discovery fail, ``fetch_avatar`` returns ``None``."""
    with patch.object(service, "_discover_avatar_url", new_callable=AsyncMock, return_value=None):
        result = await service.fetch_avatar(CHANNEL_ID)

    assert result is None


# ── is_cache_stale ───────────────────────────────────────────────────────────


def test_is_cache_stale_fresh(tmp_path: Path) -> None:
    f = tmp_path / "fresh.jpg"
    f.write_bytes(b"data")
    assert AvatarService.is_cache_stale(f, max_age_days=7) is False


def test_is_cache_stale_old(tmp_path: Path) -> None:
    f = tmp_path / "old.jpg"
    f.write_bytes(b"data")
    import os

    old_mtime = time.time() - 10 * 86_400
    os.utime(f, (old_mtime, old_mtime))
    assert AvatarService.is_cache_stale(f, max_age_days=7) is True


def test_is_cache_stale_missing(tmp_path: Path) -> None:
    """A non-existent path is considered stale."""
    assert AvatarService.is_cache_stale(tmp_path / "nope.jpg") is True


# ── get_cached_path ──────────────────────────────────────────────────────────


def test_get_cached_path_exists(service: AvatarService, tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatars"
    avatar_dir.mkdir(parents=True)
    f = avatar_dir / f"{CHANNEL_ID}.jpg"
    f.write_bytes(b"data")
    assert service.get_cached_path(CHANNEL_ID) == f


def test_get_cached_path_missing(service: AvatarService) -> None:
    assert service.get_cached_path(CHANNEL_ID) is None
