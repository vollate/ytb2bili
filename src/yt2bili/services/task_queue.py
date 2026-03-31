"""Async task queue with priority ordering, concurrency control, and retry."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import TaskStatus
from yt2bili.core.exceptions import TaskQueueError
from yt2bili.db.repository import Repository
from yt2bili.services.pipeline import Pipeline

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TaskQueue:
    """Priority-based async task queue with concurrency limiting and retry.

    Tasks are ordered by ``(priority, task_id)`` so lower priority values
    run first; ties are broken by insertion order (task_id).
    """

    def __init__(
        self,
        pipeline: Pipeline,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
    ) -> None:
        self._pipeline = pipeline
        self._session_factory = session_factory
        self._config = config

        self._queue: asyncio.PriorityQueue[tuple[int, int]] = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(config.schedule.max_concurrent_downloads)

        self._workers: list[asyncio.Task[None]] = []
        self._running_tasks: dict[int, asyncio.Task[None]] = {}
        self._cancelled: set[int] = set()
        self._stopped = False

    # ── public API ──────────────────────────────────────────────────────

    async def enqueue(self, task_id: int, priority: int = 0) -> None:
        """Add a task to the queue.

        Lower *priority* values are processed first.
        """
        if self._stopped:
            raise TaskQueueError("TaskQueue has been stopped; cannot enqueue new tasks")
        logger.info("task_queue.enqueue", task_id=task_id, priority=priority)
        await self._queue.put((priority, task_id))

    async def start_workers(self, num_workers: int) -> None:
        """Launch *num_workers* background worker coroutines."""
        if self._workers:
            raise TaskQueueError("Workers already started")
        self._stopped = False
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        logger.info("task_queue.workers_started", num_workers=num_workers)

    async def stop(self) -> None:
        """Gracefully shut down all workers and cancel pending tasks."""
        self._stopped = True
        logger.info("task_queue.stopping")

        # Cancel all running pipeline tasks
        for task_id, fut in list(self._running_tasks.items()):
            fut.cancel()
            logger.info("task_queue.cancel_running", task_id=task_id)

        # Cancel worker coroutines
        for w in self._workers:
            w.cancel()

        # Wait for workers to finish (suppress CancelledError)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._running_tasks.clear()

        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        logger.info("task_queue.stopped")

    async def cancel_task(self, task_id: int) -> bool:
        """Cancel a queued or running task.

        Returns ``True`` if the task was found and cancelled.
        """
        self._cancelled.add(task_id)

        # If running, cancel the asyncio.Task
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            logger.info("task_queue.task_cancelled_running", task_id=task_id)
            # Update DB status
            await self._update_status(task_id, TaskStatus.CANCELLED)
            return True

        # The task might still be sitting in the queue – it will be skipped
        # when dequeued because it's in self._cancelled.
        logger.info("task_queue.task_cancelled_queued", task_id=task_id)
        await self._update_status(task_id, TaskStatus.CANCELLED)
        return True

    # ── worker loop ─────────────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int) -> None:
        """Continuously dequeue and process tasks."""
        log = logger.bind(worker_id=worker_id)
        log.info("task_queue.worker_start")

        try:
            while not self._stopped:
                try:
                    priority, task_id = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                if task_id in self._cancelled:
                    self._cancelled.discard(task_id)
                    log.info("task_queue.skipped_cancelled", task_id=task_id)
                    continue

                await self._process_with_semaphore(task_id, priority, log)
        except asyncio.CancelledError:
            log.info("task_queue.worker_cancelled")
        except Exception:
            log.exception("task_queue.worker_error")

    async def _process_with_semaphore(
        self,
        task_id: int,
        priority: int,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        """Acquire semaphore, run pipeline, handle retries."""
        async with self._semaphore:
            run_task = asyncio.current_task()
            assert run_task is not None
            self._running_tasks[task_id] = run_task

            try:
                log.info("task_queue.processing", task_id=task_id)
                await self._pipeline.process_task(task_id)
                log.info("task_queue.completed", task_id=task_id)
            except asyncio.CancelledError:
                log.info("task_queue.task_cancelled_during_run", task_id=task_id)
            except Exception as exc:
                log.error("task_queue.task_failed", task_id=task_id, error=str(exc))
                await self._handle_retry(task_id, priority, log)
            finally:
                self._running_tasks.pop(task_id, None)

    async def _handle_retry(
        self,
        task_id: int,
        priority: int,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        """Check attempt count and retry with exponential backoff, or give up."""
        max_retries = self._config.schedule.max_retries
        backoff_base = self._config.schedule.retry_backoff_base

        # Read current attempt count
        async with self._session_factory() as session:
            repo = Repository(session)
            task = await repo.get_task(task_id)
            if task is None:
                return
            attempt = task.attempt

        if attempt < max_retries:
            delay = backoff_base ** attempt
            log.info(
                "task_queue.retrying",
                task_id=task_id,
                attempt=attempt,
                delay=delay,
            )
            await self._update_status(task_id, TaskStatus.RETRYING)
            await asyncio.sleep(delay)

            if task_id not in self._cancelled and not self._stopped:
                await self._queue.put((priority, task_id))
        else:
            log.warning(
                "task_queue.max_retries_reached",
                task_id=task_id,
                attempt=attempt,
            )
            await self._update_status(task_id, TaskStatus.FAILED)

    # ── helpers ─────────────────────────────────────────────────────────

    async def _update_status(self, task_id: int, status: TaskStatus) -> None:
        """Update task status in DB via a fresh session."""
        async with self._session_factory() as session:
            repo = Repository(session)
            await repo.update_task_status(task_id, status)
            await session.commit()
