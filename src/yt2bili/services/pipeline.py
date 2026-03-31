"""End-to-end video processing pipeline."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.models import Task, Video
from yt2bili.core.schemas import DownloadResult
from yt2bili.db.repository import Repository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── Service protocols (higher-level wrappers around backends) ───────────────

ProgressCallback = Callable[[float], Any]
"""A callback that receives a progress percentage (0.0 – 100.0)."""


@runtime_checkable
class VideoDownloader(Protocol):
    """Downloads a YouTube video and optional subtitles."""

    async def download(
        self,
        youtube_id: str,
        download_dir: Path,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> DownloadResult:
        """Download video. *progress_cb* is called with 0–100 values."""
        ...


@runtime_checkable
class SubtitleService(Protocol):
    """Handles subtitle extraction / generation."""

    async def process(
        self,
        video_path: Path,
        subtitle_paths: list[Path],
        subtitle_source: SubtitleSource,
        *,
        progress_cb: ProgressCallback | None = None,
    ) -> tuple[Path | None, SubtitleSource]:
        """Process subtitles. Returns (final_subtitle_path, source)."""
        ...


@runtime_checkable
class UploadService(Protocol):
    """Uploads a processed video to Bilibili."""

    async def upload_video(
        self,
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
        """Upload video. Returns the Bilibili BVid."""
        ...


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_progress_mapper(
    low: float, high: float, callback: ProgressCallback | None
) -> ProgressCallback | None:
    """Return a callback that maps 0-100 → [low, high] range, or *None*."""
    if callback is None:
        return None

    def _mapped(pct: float) -> None:
        clamped = max(0.0, min(pct, 100.0))
        callback(low + (high - low) * clamped / 100.0)

    return _mapped


# ── Pipeline ────────────────────────────────────────────────────────────────


class Pipeline:
    """Orchestrates download → subtitle → upload for a single task."""

    def __init__(
        self,
        downloader: VideoDownloader,
        subtitle_service: SubtitleService,
        upload_service: UploadService,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
    ) -> None:
        self._downloader = downloader
        self._subtitle_service = subtitle_service
        self._upload_service = upload_service
        self._session_factory = session_factory
        self._config = config

    # ── public entry point ──────────────────────────────────────────────

    async def process_task(self, task_id: int) -> None:
        """Run the full pipeline for *task_id*.

        On success the task status will be COMPLETED.
        On failure it will be FAILED with an error message.
        """
        log = logger.bind(task_id=task_id)
        log.info("pipeline.start")

        try:
            await self._run(task_id, log)
        except Exception as exc:
            log.error("pipeline.failed", error=str(exc))
            await self._mark_failed(task_id, str(exc))
            raise

    # ── internal orchestration ──────────────────────────────────────────

    async def _run(
        self,
        task_id: int,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        # (a) Load task + video + channel from DB (eager-load relationships)
        async with self._session_factory() as session:
            stmt = (
                select(Task)
                .where(Task.id == task_id)
                .options(selectinload(Task.video).selectinload(Video.channel))
            )
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            youtube_id: str = task.video.youtube_id
            video_title: str = task.video.title
            video_desc: str = task.video.description or ""
            youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            await session.commit()

        log = log.bind(youtube_id=youtube_id, video_title=video_title)

        # Helper to update status via a fresh session
        async def _update_status(
            status: TaskStatus,
            progress: float,
            **extra: object,
        ) -> None:
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(
                    task_id, status, progress_pct=progress, **extra  # type: ignore[arg-type]
                )
                await session.commit()

        async def _update_progress(pct: float) -> None:
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.DOWNLOADING, progress_pct=pct)
                await session.commit()

        # (b) DOWNLOADING, progress 0%
        log.info("pipeline.downloading")
        await _update_status(TaskStatus.DOWNLOADING, 0.0)

        # (c) Download with progress mapped to 0-40%
        download_dir = self._config.download.download_dir.expanduser()
        download_dir.mkdir(parents=True, exist_ok=True)

        async def _dl_progress(pct: float) -> None:
            mapped = max(0.0, min(pct, 100.0)) * 0.40
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(
                    task_id, TaskStatus.DOWNLOADING, progress_pct=mapped
                )
                await session.commit()

        result: DownloadResult = await self._downloader.download(
            youtube_id,
            download_dir,
            progress_cb=_dl_progress,
        )

        # (d) Update task paths
        async with self._session_factory() as session:
            repo = Repository(session)
            await repo.update_task_paths(
                task_id,
                video_path=str(result.video_path),
                subtitle_path=str(result.subtitle_paths[0]) if result.subtitle_paths else None,
                subtitle_source=result.subtitle_source.value,
            )
            await session.commit()

        log.info("pipeline.download_complete", video_path=str(result.video_path))

        # (e) SUBTITLING, progress 40%
        log.info("pipeline.subtitling")
        await _update_status(TaskStatus.SUBTITLING, 40.0)

        # (f) Subtitle processing with progress mapped to 40-60%
        async def _sub_progress(pct: float) -> None:
            mapped = 40.0 + max(0.0, min(pct, 100.0)) * 0.20
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(
                    task_id, TaskStatus.SUBTITLING, progress_pct=mapped
                )
                await session.commit()

        subtitle_path, subtitle_source = await self._subtitle_service.process(
            result.video_path,
            list(result.subtitle_paths),
            result.subtitle_source,
            progress_cb=_sub_progress,
        )

        # (g) Update subtitle info
        async with self._session_factory() as session:
            repo = Repository(session)
            await repo.update_task_paths(
                task_id,
                subtitle_path=str(subtitle_path) if subtitle_path else None,
                subtitle_source=subtitle_source.value,
            )
            await session.commit()

        log.info("pipeline.subtitle_complete", subtitle_source=subtitle_source.value)

        # (h) UPLOADING, progress 60%
        log.info("pipeline.uploading")
        await _update_status(TaskStatus.UPLOADING, 60.0)

        # (i) Upload with progress mapped to 60-95%
        upload_cfg = self._config.upload
        title = upload_cfg.title_template.format(original_title=video_title)
        desc = upload_cfg.desc_template.format(
            youtube_url=youtube_url,
            original_description=video_desc,
        )

        async def _upload_progress(pct: float) -> None:
            mapped = 60.0 + max(0.0, min(pct, 100.0)) * 0.35
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(
                    task_id, TaskStatus.UPLOADING, progress_pct=mapped
                )
                await session.commit()

        bvid: str = await self._upload_service.upload_video(
            result.video_path,
            title,
            desc,
            upload_cfg.tags,
            upload_cfg.bilibili_tid,
            subtitle_path=subtitle_path,
            source_url=youtube_url,
            progress_cb=_upload_progress,
        )

        # (j) Update BVID
        async with self._session_factory() as session:
            repo = Repository(session)
            await repo.update_task_bvid(task_id, bvid)
            await session.commit()

        log.info("pipeline.upload_complete", bvid=bvid)

        # (k) COMPLETED, progress 100%
        await _update_status(TaskStatus.COMPLETED, 100.0)
        log.info("pipeline.completed")

        # (l) Optionally clean up local files
        if self._config.upload.delete_after_upload:
            self._cleanup(result.video_path, subtitle_path)
            log.info("pipeline.cleaned_up")

    # ── failure handling ────────────────────────────────────────────────

    async def _mark_failed(self, task_id: int, error_message: str) -> None:
        """Set task to FAILED and increment attempt counter."""
        try:
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error_message=error_message,
                )
                await repo.increment_task_attempt(task_id)
                await session.commit()
        except Exception:
            logger.exception("pipeline.mark_failed_error", task_id=task_id)

    # ── file cleanup ────────────────────────────────────────────────────

    @staticmethod
    def _cleanup(video_path: Path, subtitle_path: Path | None) -> None:
        """Remove local files after successful upload."""
        for p in (video_path, subtitle_path):
            if p is not None and p.exists():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
