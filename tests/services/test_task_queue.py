"""Tests for the TaskQueue class."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yt2bili.core.config import AppConfig, ScheduleConfig
from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.models import Base
from yt2bili.core.schemas import ChannelCreate, DownloadResult, VideoMeta
from yt2bili.db.repository import Repository
from yt2bili.services.pipeline import Pipeline
from yt2bili.services.task_queue import TaskQueue

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


async def _seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    priority: int = 0,
    youtube_id: str = "vid1",
) -> int:
    async with session_factory() as session:
        repo = Repository(session)
        # Reuse channel if exists
        channel = await repo.get_channel_by_youtube_id("UC_test")
        if channel is None:
            channel = await repo.create_channel(
                ChannelCreate(youtube_channel_id="UC_test", name="Test")
            )
        video = await repo.create_video(
            channel.id,
            VideoMeta(youtube_id=youtube_id, title=f"Video {youtube_id}"),
        )
        task = await repo.create_task(video.id, priority=priority)
        await session.commit()
        return task.id


# ── Tests: enqueue / dequeue ordering ───────────────────────────────────────


async def test_enqueue_dequeue_priority_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Lower priority values should be dequeued first."""
    process_order: list[int] = []

    mock_pipeline = MagicMock(spec=Pipeline)

    async def _process(task_id: int) -> None:
        process_order.append(task_id)

    mock_pipeline.process_task = AsyncMock(side_effect=_process)

    config = AppConfig(schedule=ScheduleConfig(max_concurrent_downloads=1))
    tq = TaskQueue(mock_pipeline, session_factory, config)

    t1 = await _seed_task(session_factory, priority=10, youtube_id="low_prio")
    t2 = await _seed_task(session_factory, priority=1, youtube_id="high_prio")
    t3 = await _seed_task(session_factory, priority=5, youtube_id="mid_prio")

    await tq.enqueue(t1, priority=10)
    await tq.enqueue(t2, priority=1)
    await tq.enqueue(t3, priority=5)

    await tq.start_workers(1)
    # Give workers time to drain the queue
    await asyncio.sleep(0.5)
    await tq.stop()

    assert process_order == [t2, t3, t1], f"Expected priority ordering, got {process_order}"


# ── Tests: concurrency limits ───────────────────────────────────────────────


async def test_concurrency_semaphore(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the semaphore limits concurrent pipeline executions."""
    max_concurrent = 2
    concurrent_count = 0
    peak_concurrent = 0
    lock = asyncio.Lock()

    mock_pipeline = MagicMock(spec=Pipeline)

    async def _process(task_id: int) -> None:
        nonlocal concurrent_count, peak_concurrent
        async with lock:
            concurrent_count += 1
            peak_concurrent = max(peak_concurrent, concurrent_count)
        await asyncio.sleep(0.1)  # Simulate work
        async with lock:
            concurrent_count -= 1

    mock_pipeline.process_task = AsyncMock(side_effect=_process)

    config = AppConfig(schedule=ScheduleConfig(max_concurrent_downloads=max_concurrent))
    tq = TaskQueue(mock_pipeline, session_factory, config)

    # Enqueue more tasks than concurrency limit
    task_ids = []
    for i in range(5):
        tid = await _seed_task(session_factory, youtube_id=f"conc_{i}")
        task_ids.append(tid)
        await tq.enqueue(tid, priority=0)

    await tq.start_workers(4)  # More workers than semaphore allows
    await asyncio.sleep(1.0)
    await tq.stop()

    assert peak_concurrent <= max_concurrent, (
        f"Peak concurrency {peak_concurrent} exceeded limit {max_concurrent}"
    )
    assert mock_pipeline.process_task.await_count == 5


# ── Tests: retry with backoff ──────────────────────────────────────────────


async def test_retry_on_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify retry logic: task retried up to max_retries times with backoff."""
    call_count = 0

    mock_pipeline = MagicMock(spec=Pipeline)

    async def _process(task_id: int) -> None:
        nonlocal call_count
        call_count += 1
        # Simulate the pipeline incrementing attempt on failure
        async with session_factory() as session:
            repo = Repository(session)
            await repo.increment_task_attempt(task_id)
            await session.commit()
        raise RuntimeError("transient error")

    mock_pipeline.process_task = AsyncMock(side_effect=_process)

    config = AppConfig(
        schedule=ScheduleConfig(
            max_retries=3,
            retry_backoff_base=0.01,  # Very small for fast tests
            max_concurrent_downloads=2,
        )
    )
    tq = TaskQueue(mock_pipeline, session_factory, config)

    tid = await _seed_task(session_factory, youtube_id="retry_test")
    await tq.enqueue(tid, priority=0)

    await tq.start_workers(1)
    # Allow enough time for retries with tiny backoff
    await asyncio.sleep(2.0)
    await tq.stop()

    # Should be called: initial + max_retries retries
    # attempt starts at 0, incremented each failure:
    # call 1: attempt=0 → inc to 1, retry (attempt 1 < 3)
    # call 2: attempt=1 → inc to 2, retry (attempt 2 < 3)
    # call 3: attempt=2 → inc to 3, retry (attempt 3 >= 3) → FAILED
    assert call_count >= 3, f"Expected at least 3 calls, got {call_count}"


async def test_max_retries_exceeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify task is marked FAILED when max retries exceeded."""
    mock_pipeline = MagicMock(spec=Pipeline)

    async def _process(task_id: int) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.increment_task_attempt(task_id)
            await session.commit()
        raise RuntimeError("permanent error")

    mock_pipeline.process_task = AsyncMock(side_effect=_process)

    config = AppConfig(
        schedule=ScheduleConfig(
            max_retries=2,
            retry_backoff_base=0.01,
            max_concurrent_downloads=1,
        )
    )
    tq = TaskQueue(mock_pipeline, session_factory, config)

    tid = await _seed_task(session_factory, youtube_id="max_retry_test")
    await tq.enqueue(tid, priority=0)

    await tq.start_workers(1)
    await asyncio.sleep(2.0)
    await tq.stop()

    async with session_factory() as session:
        repo = Repository(session)
        task = await repo.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.FAILED


# ── Tests: cancellation ────────────────────────────────────────────────────


async def test_cancel_queued_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a queued task can be cancelled before processing."""
    mock_pipeline = MagicMock(spec=Pipeline)

    async def _process(task_id: int) -> None:
        await asyncio.sleep(10)  # Long-running, should not complete

    mock_pipeline.process_task = AsyncMock(side_effect=_process)

    config = AppConfig(schedule=ScheduleConfig(max_concurrent_downloads=1))
    tq = TaskQueue(mock_pipeline, session_factory, config)

    tid = await _seed_task(session_factory, youtube_id="cancel_test")
    await tq.enqueue(tid, priority=0)

    # Cancel before workers start
    result = await tq.cancel_task(tid)
    assert result is True

    await tq.start_workers(1)
    await asyncio.sleep(0.3)
    await tq.stop()

    # process_task should never have been called for the cancelled task
    mock_pipeline.process_task.assert_not_awaited()


async def test_stop_graceful(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify stop() cancels workers and drains the queue."""
    mock_pipeline = MagicMock(spec=Pipeline)
    mock_pipeline.process_task = AsyncMock()

    config = AppConfig()
    tq = TaskQueue(mock_pipeline, session_factory, config)

    await tq.start_workers(2)
    await tq.stop()

    # Should not raise when stopping already-stopped queue
    assert tq._stopped is True
    assert len(tq._workers) == 0


async def test_enqueue_after_stop_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify enqueue raises after stop."""
    from yt2bili.core.exceptions import TaskQueueError

    mock_pipeline = MagicMock(spec=Pipeline)
    config = AppConfig()
    tq = TaskQueue(mock_pipeline, session_factory, config)
    await tq.stop()

    with pytest.raises(TaskQueueError):
        await tq.enqueue(1, priority=0)
