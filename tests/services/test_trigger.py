"""Tests for yt2bili.services.trigger – TriggerService."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import TaskStatus
from yt2bili.core.models import Task, Video
from yt2bili.core.schemas import VideoMeta
from yt2bili.db.repository import Repository
from yt2bili.services.trigger import TriggerService


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_channel(
    *,
    channel_id: int = 1,
    youtube_channel_id: str = "UC_test",
    name: str = "Test",
    enabled: bool = True,
) -> MagicMock:
    ch = MagicMock()
    ch.id = channel_id
    ch.youtube_channel_id = youtube_channel_id
    ch.name = name
    ch.enabled = enabled
    return ch


def _make_video(video_id: int = 10, youtube_id: str = "yt_vid_1") -> MagicMock:
    v = MagicMock(spec=Video)
    v.id = video_id
    v.youtube_id = youtube_id
    v.title = "Test Video"
    v.description = "desc"
    v.duration = None
    v.youtube_upload_date = None
    v.thumbnail_url = None
    v.channel_id = 1
    return v


def _make_task(
    task_id: int = 100,
    video_id: int = 10,
    status: TaskStatus = TaskStatus.PENDING,
    priority: int = 0,
) -> MagicMock:
    t = MagicMock(spec=Task)
    t.id = task_id
    t.video_id = video_id
    t.status = status
    t.priority = priority
    t.attempt = 0
    return t


def _mock_session_factory() -> MagicMock:
    """Return a mock async_sessionmaker that yields a mock session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _mock_task_queue() -> MagicMock:
    tq = MagicMock()
    tq.enqueue = AsyncMock()
    tq.cancel_task = AsyncMock(return_value=True)
    return tq


# ── check_channel ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_channel_creates_tasks_for_new_videos() -> None:
    """check_channel should persist new videos and create PENDING tasks."""
    factory = _mock_session_factory()
    tq = _mock_task_queue()
    config = AppConfig()

    channel = _make_channel()
    video1 = _make_video(video_id=10, youtube_id="yt_1")
    video2 = _make_video(video_id=11, youtube_id="yt_2")
    task1 = _make_task(task_id=100, video_id=10)
    task2 = _make_task(task_id=101, video_id=11)

    with patch("yt2bili.services.trigger.Repository") as MockRepo, \
         patch("yt2bili.services.trigger.ChannelMonitor") as MockMonitor:

        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_channel = AsyncMock(return_value=channel)
        repo_instance.create_task = AsyncMock(side_effect=[task1, task2])
        repo_instance.update_channel_checked = AsyncMock()
        MockRepo.return_value = repo_instance

        monitor_instance = MagicMock()
        monitor_instance.check_channel_and_persist = AsyncMock(return_value=[video1, video2])
        MockMonitor.return_value = monitor_instance

        svc = TriggerService(factory, config, task_queue=tq)
        result = await svc.check_channel(channel_id=1)

    assert len(result) == 2
    assert all(isinstance(v, VideoMeta) for v in result)
    assert repo_instance.create_task.call_count == 2
    assert tq.enqueue.call_count == 2


@pytest.mark.asyncio
async def test_check_channel_returns_empty_when_not_found() -> None:
    """check_channel should return [] when the channel does not exist."""
    factory = _mock_session_factory()
    config = AppConfig()

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_channel = AsyncMock(return_value=None)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.check_channel(channel_id=999)

    assert result == []


# ── check_all_channels ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_all_channels_iterates_enabled() -> None:
    """check_all_channels should iterate every enabled channel."""
    factory = _mock_session_factory()
    config = AppConfig()

    ch1 = _make_channel(channel_id=1)
    ch2 = _make_channel(channel_id=2)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.list_channels = AsyncMock(return_value=[ch1, ch2])
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        # Mock check_channel to avoid real RSS
        svc.check_channel = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                [VideoMeta(youtube_id="v1", title="V1")],
                [VideoMeta(youtube_id="v2", title="V2")],
            ]
        )
        result = await svc.check_all_channels()

    assert result["channels_checked"] == 2
    assert result["new_videos"] == 2
    assert result["tasks_created"] == 2
    assert svc.check_channel.call_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_check_all_channels_continues_on_error() -> None:
    """If one channel fails, other channels should still be checked."""
    factory = _mock_session_factory()
    config = AppConfig()

    ch1 = _make_channel(channel_id=1)
    ch2 = _make_channel(channel_id=2)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.list_channels = AsyncMock(return_value=[ch1, ch2])
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        svc.check_channel = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                Exception("boom"),
                [VideoMeta(youtube_id="v2", title="V2")],
            ]
        )
        result = await svc.check_all_channels()

    assert result["channels_checked"] == 2
    assert result["new_videos"] == 1


# ── create_task_for_video ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_for_video_creates_and_enqueues() -> None:
    """create_task_for_video should create a DB task and enqueue it."""
    factory = _mock_session_factory()
    tq = _mock_task_queue()
    config = AppConfig()

    video = _make_video(video_id=10)
    task = _make_task(task_id=100, video_id=10, priority=5)

    # Make the session.get return the video
    session = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=video)
    factory.return_value.__aenter__ = AsyncMock(return_value=session)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.create_task = AsyncMock(return_value=task)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config, task_queue=tq)
        result = await svc.create_task_for_video(video_id=10, priority=5)

    assert result.id == 100
    repo_instance.create_task.assert_awaited_once_with(10, priority=5)
    tq.enqueue.assert_awaited_once_with(100, 5)


@pytest.mark.asyncio
async def test_create_task_for_video_raises_when_not_found() -> None:
    """create_task_for_video should raise ValueError for missing video."""
    factory = _mock_session_factory()
    config = AppConfig()

    with patch("yt2bili.services.trigger.Repository"):
        svc = TriggerService(factory, config)
        with pytest.raises(ValueError, match="Video 999 not found"):
            await svc.create_task_for_video(video_id=999)


# ── retry_task ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_task_resets_failed_to_pending() -> None:
    """retry_task should reset a FAILED task to PENDING."""
    factory = _mock_session_factory()
    tq = _mock_task_queue()
    config = AppConfig()

    failed_task = _make_task(task_id=100, status=TaskStatus.FAILED)
    failed_task.attempt = 3

    reset_task = _make_task(task_id=100, status=TaskStatus.PENDING)
    reset_task.attempt = 0

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(side_effect=[failed_task, reset_task])
        repo_instance.update_task_status = AsyncMock()
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config, task_queue=tq)
        result = await svc.retry_task(task_id=100)

    assert result is not None
    assert result.id == 100
    repo_instance.update_task_status.assert_awaited_once_with(
        100, TaskStatus.PENDING, progress_pct=0.0, error_message=""
    )
    tq.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_task_returns_none_for_non_failed() -> None:
    """retry_task should return None if the task is not FAILED."""
    factory = _mock_session_factory()
    config = AppConfig()

    pending_task = _make_task(task_id=100, status=TaskStatus.PENDING)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=pending_task)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.retry_task(task_id=100)

    assert result is None


@pytest.mark.asyncio
async def test_retry_task_returns_none_when_not_found() -> None:
    """retry_task should return None if the task does not exist."""
    factory = _mock_session_factory()
    config = AppConfig()

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=None)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.retry_task(task_id=999)

    assert result is None


# ── cancel_task ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_task_updates_status() -> None:
    """cancel_task should set a PENDING task to CANCELLED."""
    factory = _mock_session_factory()
    tq = _mock_task_queue()
    config = AppConfig()

    pending_task = _make_task(task_id=100, status=TaskStatus.PENDING)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=pending_task)
        repo_instance.update_task_status = AsyncMock()
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config, task_queue=tq)
        result = await svc.cancel_task(task_id=100)

    assert result is True
    repo_instance.update_task_status.assert_awaited_once_with(100, TaskStatus.CANCELLED)
    tq.cancel_task.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_cancel_task_rejects_completed() -> None:
    """cancel_task should return False for a COMPLETED task."""
    factory = _mock_session_factory()
    config = AppConfig()

    done_task = _make_task(task_id=100, status=TaskStatus.COMPLETED)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=done_task)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.cancel_task(task_id=100)

    assert result is False


@pytest.mark.asyncio
async def test_cancel_task_returns_false_when_not_found() -> None:
    """cancel_task should return False if the task does not exist."""
    factory = _mock_session_factory()
    config = AppConfig()

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=None)
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.cancel_task(task_id=999)

    assert result is False


@pytest.mark.asyncio
async def test_cancel_retrying_task() -> None:
    """cancel_task should also work for RETRYING tasks."""
    factory = _mock_session_factory()
    config = AppConfig()

    retrying_task = _make_task(task_id=100, status=TaskStatus.RETRYING)

    with patch("yt2bili.services.trigger.Repository") as MockRepo:
        repo_instance = MagicMock(spec=Repository)
        repo_instance.get_task = AsyncMock(return_value=retrying_task)
        repo_instance.update_task_status = AsyncMock()
        MockRepo.return_value = repo_instance

        svc = TriggerService(factory, config)
        result = await svc.cancel_task(task_id=100)

    assert result is True
    repo_instance.update_task_status.assert_awaited_once_with(100, TaskStatus.CANCELLED)
