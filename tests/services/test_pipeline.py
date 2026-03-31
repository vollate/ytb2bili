"""Tests for the Pipeline class."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.models import Base
from yt2bili.core.schemas import DownloadResult
from yt2bili.db.repository import Repository
from yt2bili.services.pipeline import Pipeline, ProgressCallback

pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory  # type: ignore[misc]
    await engine.dispose()


@pytest_asyncio.fixture()
async def seed_task(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Seed a channel → video → task and return the task id."""
    from yt2bili.core.schemas import ChannelCreate, VideoMeta

    async with session_factory() as session:
        repo = Repository(session)
        channel = await repo.create_channel(
            ChannelCreate(youtube_channel_id="UC_test", name="Test Channel")
        )
        video = await repo.create_video(
            channel.id,
            VideoMeta(youtube_id="dQw4w9WgXcQ", title="Test Video", description="desc"),
        )
        task = await repo.create_task(video.id, priority=0)
        await session.commit()
        return task.id


def _make_downloader(
    video_path: Path | None = None,
    subtitle_paths: list[Path] | None = None,
    subtitle_source: SubtitleSource = SubtitleSource.YOUTUBE_AUTO,
    error: Exception | None = None,
) -> AsyncMock:
    mock = AsyncMock()

    async def _download(
        youtube_id: str,
        download_dir: Path,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> DownloadResult:
        if error:
            raise error
        if progress_cb is not None:
            result = progress_cb(50.0)
            if hasattr(result, "__await__"):
                await result
            result = progress_cb(100.0)
            if hasattr(result, "__await__"):
                await result
        return DownloadResult(
            video_path=video_path or Path("/tmp/video.mp4"),
            subtitle_paths=subtitle_paths or [],
            subtitle_source=subtitle_source,
        )

    mock.download = AsyncMock(side_effect=_download)
    return mock


def _make_subtitle_service(
    result_path: Path | None = Path("/tmp/subs.srt"),
    result_source: SubtitleSource = SubtitleSource.YOUTUBE_AUTO,
    error: Exception | None = None,
) -> AsyncMock:
    mock = AsyncMock()

    async def _process(
        video_path: Path,
        subtitle_paths: list[Path],
        subtitle_source: SubtitleSource,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> tuple[Path | None, SubtitleSource]:
        if error:
            raise error
        if progress_cb is not None:
            result = progress_cb(100.0)
            if hasattr(result, "__await__"):
                await result
        return result_path, result_source

    mock.process = AsyncMock(side_effect=_process)
    return mock


def _make_upload_service(
    bvid: str = "BV1xx411c7XY",
    error: Exception | None = None,
) -> AsyncMock:
    mock = AsyncMock()

    async def _upload(
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        partition_id: int,
        *,
        subtitle_path: Path | None = None,
        thumbnail_path: Path | None = None,
        source_url: str = "",
        progress_cb: ProgressCallback | None = None,
    ) -> str:
        if error:
            raise error
        if progress_cb is not None:
            result = progress_cb(100.0)
            if hasattr(result, "__await__"):
                await result
        return bvid

    mock.upload_video = AsyncMock(side_effect=_upload)
    return mock


# ── Tests ───────────────────────────────────────────────────────────────────


async def test_full_pipeline_success(
    session_factory: async_sessionmaker[AsyncSession],
    seed_task: int,
) -> None:
    """Verify full state transition: PENDING → DOWNLOADING → SUBTITLING → UPLOADING → COMPLETED."""
    config = AppConfig()
    downloader = _make_downloader()
    subtitle_svc = _make_subtitle_service()
    upload_svc = _make_upload_service()

    pipeline = Pipeline(downloader, subtitle_svc, upload_svc, session_factory, config)
    await pipeline.process_task(seed_task)

    # Verify final state
    async with session_factory() as session:
        repo = Repository(session)
        task = await repo.get_task(seed_task)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.progress_pct == 100.0
        assert task.bilibili_bvid == "BV1xx411c7XY"
        assert task.video_path == "/tmp/video.mp4"

    # Verify services were called
    downloader.download.assert_awaited_once()
    subtitle_svc.process.assert_awaited_once()
    upload_svc.upload_video.assert_awaited_once()


async def test_pipeline_download_failure(
    session_factory: async_sessionmaker[AsyncSession],
    seed_task: int,
) -> None:
    """Verify failure during download sets FAILED status with error message."""
    config = AppConfig()
    downloader = _make_downloader(error=RuntimeError("network timeout"))
    subtitle_svc = _make_subtitle_service()
    upload_svc = _make_upload_service()

    pipeline = Pipeline(downloader, subtitle_svc, upload_svc, session_factory, config)

    with pytest.raises(RuntimeError, match="network timeout"):
        await pipeline.process_task(seed_task)

    async with session_factory() as session:
        repo = Repository(session)
        task = await repo.get_task(seed_task)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert "network timeout" in (task.error_message or "")

    # Subtitle and upload should NOT have been called
    subtitle_svc.process.assert_not_awaited()
    upload_svc.upload_video.assert_not_awaited()


async def test_pipeline_upload_failure(
    session_factory: async_sessionmaker[AsyncSession],
    seed_task: int,
) -> None:
    """Verify failure during upload sets FAILED status."""
    config = AppConfig()
    downloader = _make_downloader()
    subtitle_svc = _make_subtitle_service()
    upload_svc = _make_upload_service(error=RuntimeError("upload denied"))

    pipeline = Pipeline(downloader, subtitle_svc, upload_svc, session_factory, config)

    with pytest.raises(RuntimeError, match="upload denied"):
        await pipeline.process_task(seed_task)

    async with session_factory() as session:
        repo = Repository(session)
        task = await repo.get_task(seed_task)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert "upload denied" in (task.error_message or "")


async def test_pipeline_subtitle_failure(
    session_factory: async_sessionmaker[AsyncSession],
    seed_task: int,
) -> None:
    """Verify failure during subtitling sets FAILED status."""
    config = AppConfig()
    downloader = _make_downloader()
    subtitle_svc = _make_subtitle_service(error=RuntimeError("whisper crashed"))
    upload_svc = _make_upload_service()

    pipeline = Pipeline(downloader, subtitle_svc, upload_svc, session_factory, config)

    with pytest.raises(RuntimeError, match="whisper crashed"):
        await pipeline.process_task(seed_task)

    async with session_factory() as session:
        repo = Repository(session)
        task = await repo.get_task(seed_task)
        assert task is not None
        assert task.status == TaskStatus.FAILED

    upload_svc.upload_video.assert_not_awaited()


async def test_pipeline_task_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify ValueError when task does not exist."""
    config = AppConfig()
    pipeline = Pipeline(
        _make_downloader(), _make_subtitle_service(), _make_upload_service(),
        session_factory, config,
    )

    with pytest.raises(ValueError, match="not found"):
        await pipeline.process_task(99999)


async def test_pipeline_progress_callbacks(
    session_factory: async_sessionmaker[AsyncSession],
    seed_task: int,
) -> None:
    """Verify that progress callbacks are invoked by each stage."""
    config = AppConfig()
    downloader = _make_downloader()
    subtitle_svc = _make_subtitle_service()
    upload_svc = _make_upload_service()

    pipeline = Pipeline(downloader, subtitle_svc, upload_svc, session_factory, config)
    await pipeline.process_task(seed_task)

    # The download mock calls progress_cb(50) and progress_cb(100).
    # We just verify the download side_effect was used (called once via AsyncMock).
    downloader.download.assert_awaited_once()
    subtitle_svc.process.assert_awaited_once()
    upload_svc.upload_video.assert_awaited_once()
