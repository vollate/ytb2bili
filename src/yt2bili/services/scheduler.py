"""APScheduler-based periodic scheduling service."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from yt2bili.core.config import AppConfig
    from yt2bili.services.monitor import ChannelMonitor

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MAIN_JOB_ID = "check_all_channels"
_CHANNEL_JOB_PREFIX = "check_channel_"


class SchedulerService:
    """Wraps APScheduler to periodically poll YouTube channels."""

    def __init__(self, monitor: ChannelMonitor, config: AppConfig) -> None:
        self._monitor = monitor
        self._config = config
        self._scheduler = AsyncIOScheduler()
        self._running: bool = False
        self._last_check_time: datetime.datetime | None = None
        self._last_new_videos_count: int = 0

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler and add the main polling job."""
        interval_minutes = self._config.schedule.poll_interval_minutes
        self._scheduler.add_job(
            self._run_check_all,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=_MAIN_JOB_ID,
            replace_existing=True,
            name="Poll all enabled channels",
        )
        self._scheduler.start()
        self._running = True
        logger.info("scheduler_started", poll_interval_minutes=interval_minutes)

    def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            # Replace with a fresh instance so start() can be called again later
            self._scheduler = AsyncIOScheduler()
            self._running = False
            logger.info("scheduler_stopped")

    async def trigger_now(self) -> None:
        """Immediately trigger a full channel check (outside the schedule)."""
        logger.info("scheduler_trigger_now")
        await self._run_check_all()

    async def check_all(self) -> None:
        """Alias for :meth:`trigger_now` (called by the web UI callback)."""
        await self.trigger_now()

    # ── per-channel job management ──────────────────────────────────────

    def add_channel_job(self, channel_id: int, interval_minutes: int | None = None) -> None:
        """Add a dedicated polling job for a single channel.

        If *interval_minutes* is ``None``, the global poll interval is used.
        """
        interval = interval_minutes or self._config.schedule.poll_interval_minutes
        job_id = f"{_CHANNEL_JOB_PREFIX}{channel_id}"
        self._scheduler.add_job(
            self._run_check_channel,
            trigger=IntervalTrigger(minutes=interval),
            args=[channel_id],
            id=job_id,
            replace_existing=True,
            name=f"Poll channel {channel_id}",
        )
        logger.info("channel_job_added", channel_id=channel_id, interval_minutes=interval)

    def remove_channel_job(self, channel_id: int) -> None:
        """Remove the dedicated polling job for *channel_id*, if it exists."""
        job_id = f"{_CHANNEL_JOB_PREFIX}{channel_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("channel_job_removed", channel_id=channel_id)
        except Exception:
            logger.debug("channel_job_not_found", channel_id=channel_id)

    # ── internal runners ────────────────────────────────────────────────

    async def _run_check_all(self) -> None:
        """Wrapper around monitor.check_all_channels with error handling."""
        try:
            new_videos = await self._monitor.check_all_channels()
            self._last_check_time = datetime.datetime.now(tz=datetime.timezone.utc)
            self._last_new_videos_count = len(new_videos)
            logger.info("scheduled_check_complete", new_video_count=len(new_videos))
        except Exception:
            logger.exception("scheduled_check_failed")

    async def _run_check_channel(self, channel_id: int) -> None:
        """Wrapper for a single-channel check triggered by a per-channel job."""
        try:
            channel = await self._monitor._repo.get_channel(channel_id)
            if channel is None or not channel.enabled:
                logger.warning("channel_job_skip", channel_id=channel_id, reason="not found or disabled")
                return
            new_videos = await self._monitor.check_channel(channel)
            logger.info(
                "channel_job_check_complete",
                channel_id=channel_id,
                new_video_count=len(new_videos),
            )
        except Exception:
            logger.exception("channel_job_check_failed", channel_id=channel_id)

    @property
    def running(self) -> bool:
        """Return whether the scheduler is currently running."""
        return self._running

    @property
    def last_check_time(self) -> datetime.datetime | None:
        """UTC datetime of the most recent completed check, or ``None``."""
        return self._last_check_time

    @property
    def last_new_videos_count(self) -> int:
        """Number of new videos found during the last completed check."""
        return self._last_new_videos_count
