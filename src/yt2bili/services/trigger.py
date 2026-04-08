"""Manual trigger service for channel checks and task management."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog

from yt2bili.core.enums import TaskStatus
from yt2bili.core.models import Task, Video
from yt2bili.core.schemas import VideoMeta
from yt2bili.db.repository import Repository
from yt2bili.services.monitor import ChannelMonitor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from yt2bili.core.config import AppConfig
    from yt2bili.services.task_queue import TaskQueue

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TriggerService:
    """Orchestrates manual channel checks and task management actions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
        task_queue: TaskQueue | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._task_queue = task_queue

    async def check_channel(self, channel_id: int) -> list[VideoMeta]:
        """Manually trigger RSS check for a single channel.

        Creates a temporary :class:`ChannelMonitor`, fetches the RSS feed,
        inserts new videos into the DB, creates PENDING tasks for each, and
        optionally enqueues them.  Returns the list of new videos found.
        """
        log = logger.bind(channel_id=channel_id)
        log.info("trigger.check_channel_start")

        async with self._session_factory() as session:
            repo = Repository(session)
            channel = await repo.get_channel(channel_id)
            if channel is None:
                log.warning("trigger.channel_not_found")
                return []

            monitor = ChannelMonitor(repo=repo, config=self._config)
            new_videos = await monitor.check_channel_and_persist(channel)

            # Create a PENDING task for every newly discovered video.
            created_tasks: list[Task] = []
            for video in new_videos:
                task = await repo.create_task(video.id)
                created_tasks.append(task)
                log.info("trigger.task_created", task_id=task.id, video_id=video.id)

            await repo.update_channel_checked(
                channel_id, datetime.datetime.now(tz=datetime.timezone.utc)
            )
            await session.commit()

        # Enqueue outside the session so the DB rows are visible.
        if self._task_queue is not None:
            for task in created_tasks:
                await self._task_queue.enqueue(task.id, task.priority)

        metas = [
            VideoMeta(
                youtube_id=v.youtube_id,
                title=v.title,
                description=v.description,
                duration=v.duration,
                youtube_upload_date=v.youtube_upload_date,
                thumbnail_url=v.thumbnail_url,
            )
            for v in new_videos
        ]
        log.info("trigger.check_channel_done", new_count=len(metas))
        return metas

    async def check_all_channels(self) -> dict[str, int]:
        """Check all enabled channels for new videos.

        Returns a summary dict::

            {"channels_checked": N, "new_videos": M, "tasks_created": K}
        """
        log = logger.bind()
        log.info("trigger.check_all_start")

        channels_checked = 0
        total_new_videos = 0
        total_tasks_created = 0

        async with self._session_factory() as session:
            repo = Repository(session)
            channels = await repo.list_channels(enabled_only=True)

        for channel in channels:
            try:
                new_videos = await self.check_channel(channel.id)
                total_new_videos += len(new_videos)
                total_tasks_created += len(new_videos)
            except Exception:
                log.exception("trigger.check_channel_failed", channel_id=channel.id)
            finally:
                channels_checked += 1

        result: dict[str, int] = {
            "channels_checked": channels_checked,
            "new_videos": total_new_videos,
            "tasks_created": total_tasks_created,
        }
        log.info("trigger.check_all_done", **result)
        return result

    async def create_task_for_video(
        self, video_id: int, priority: int = 0
    ) -> Task:
        """Manually create a processing task for an existing video.

        Enqueues the task if a :class:`TaskQueue` is available.
        """
        log = logger.bind(video_id=video_id, priority=priority)
        log.info("trigger.create_task_start")

        async with self._session_factory() as session:
            repo = Repository(session)
            video = await session.get(Video, video_id)
            if video is None:
                raise ValueError(f"Video {video_id} not found")

            task = await repo.create_task(video_id, priority=priority)
            await session.commit()
            log.info("trigger.create_task_done", task_id=task.id)

        if self._task_queue is not None:
            await self._task_queue.enqueue(task.id, task.priority)

        return task

    async def retry_task(self, task_id: int) -> Task | None:
        """Reset a FAILED or CANCELLED task to PENDING and re-enqueue it.

        Returns the updated :class:`Task`, or ``None`` if the task was not
        found or is not in a retryable status.
        """
        log = logger.bind(task_id=task_id)
        log.info("trigger.retry_task_start")

        async with self._session_factory() as session:
            repo = Repository(session)
            task = await repo.get_task(task_id)
            if task is None:
                log.warning("trigger.retry_task_not_found")
                return None
            if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                log.warning("trigger.retry_task_not_retryable", status=task.status.value)
                return None

            await repo.update_task_status(task_id, TaskStatus.PENDING, progress_pct=0.0, error_message="")
            task.attempt = 0
            await session.commit()

            # Re-read to get fresh state
            task = await repo.get_task(task_id)
            log.info("trigger.retry_task_done")

        if self._task_queue is not None and task is not None:
            await self._task_queue.enqueue(task.id, task.priority)

        return task

    async def cancel_task(self, task_id: int) -> bool:
        """Cancel a PENDING, RETRYING, or active (DOWNLOADING/UPLOADING/SUBTITLING) task.

        For active tasks the cancellation is delegated to the :class:`TaskQueue`
        which cancels the running ``asyncio.Task`` and updates the DB status.
        For queued tasks the status is set to CANCELLED directly.

        Returns ``True`` if the task was successfully cancelled.
        """
        log = logger.bind(task_id=task_id)
        log.info("trigger.cancel_task_start")

        _CANCELLABLE = (
            TaskStatus.PENDING,
            TaskStatus.RETRYING,
            TaskStatus.DOWNLOADING,
            TaskStatus.SUBTITLING,
            TaskStatus.UPLOADING,
        )

        async with self._session_factory() as session:
            repo = Repository(session)
            task = await repo.get_task(task_id)
            if task is None:
                log.warning("trigger.cancel_task_not_found")
                return False
            if task.status not in _CANCELLABLE:
                log.warning("trigger.cancel_task_invalid_status", status=task.status.value)
                return False

        # For active tasks, delegate to task_queue which can cancel the running
        # asyncio.Task and update the DB status atomically.
        if self._task_queue is not None:
            await self._task_queue.cancel_task(task_id)
        else:
            # No task queue — just update DB directly
            async with self._session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.CANCELLED)
                await session.commit()

        log.info("trigger.cancel_task_done")
        return True
