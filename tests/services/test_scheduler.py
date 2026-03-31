"""Tests for yt2bili.services.scheduler – SchedulerService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from yt2bili.core.config import AppConfig
from yt2bili.services.monitor import ChannelMonitor
from yt2bili.services.scheduler import SchedulerService, _CHANNEL_JOB_PREFIX, _MAIN_JOB_ID


def _make_scheduler_service() -> tuple[SchedulerService, MagicMock, AppConfig]:
    """Create a SchedulerService with a mocked ChannelMonitor."""
    monitor = MagicMock(spec=ChannelMonitor)
    monitor.check_all_channels = AsyncMock(return_value=[])
    monitor._repo = MagicMock()
    monitor._repo.get_channel = AsyncMock(return_value=None)
    config = AppConfig()
    svc = SchedulerService(monitor=monitor, config=config)
    return svc, monitor, config


class TestSchedulerLifecycle:
    """Test start / stop / running property."""

    @pytest.mark.asyncio
    async def test_start_adds_job_and_starts(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        assert svc.running is True
        job = svc._scheduler.get_job(_MAIN_JOB_ID)
        assert job is not None
        svc.stop()

    @pytest.mark.asyncio
    async def test_stop_shuts_down(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        assert svc.running is True
        svc.stop()
        assert svc.running is False

    def test_stop_when_not_running_is_noop(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.stop()
        assert svc.running is False


class TestTriggerNow:
    """Test the trigger_now convenience method."""

    @pytest.mark.asyncio
    async def test_trigger_now_calls_check_all(self) -> None:
        svc, monitor, _config = _make_scheduler_service()
        await svc.trigger_now()
        monitor.check_all_channels.assert_awaited_once()


class TestChannelJobs:
    """Test per-channel job add / remove."""

    @pytest.mark.asyncio
    async def test_add_channel_job(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        svc.add_channel_job(channel_id=42)
        job = svc._scheduler.get_job(f"{_CHANNEL_JOB_PREFIX}42")
        assert job is not None
        svc.stop()

    @pytest.mark.asyncio
    async def test_add_channel_job_custom_interval(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        svc.add_channel_job(channel_id=7, interval_minutes=5)
        job = svc._scheduler.get_job(f"{_CHANNEL_JOB_PREFIX}7")
        assert job is not None
        svc.stop()

    @pytest.mark.asyncio
    async def test_remove_channel_job(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        svc.add_channel_job(channel_id=42)
        svc.remove_channel_job(channel_id=42)
        job = svc._scheduler.get_job(f"{_CHANNEL_JOB_PREFIX}42")
        assert job is None
        svc.stop()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_channel_job_no_error(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        svc.remove_channel_job(channel_id=999)
        svc.stop()

    @pytest.mark.asyncio
    async def test_add_channel_job_replace_existing(self) -> None:
        svc, _monitor, _config = _make_scheduler_service()
        svc.start()
        svc.add_channel_job(channel_id=42, interval_minutes=10)
        svc.add_channel_job(channel_id=42, interval_minutes=5)
        job = svc._scheduler.get_job(f"{_CHANNEL_JOB_PREFIX}42")
        assert job is not None
        svc.stop()
