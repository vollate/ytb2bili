"""Task queue and history page — filterable table with progress + actions."""

from __future__ import annotations

from typing import Any, Callable

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.db.repository import Repository
from yt2bili.web.components.task_row import render_task_row

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_FILTER_OPTIONS: list[str] = ["all"] + [s.value for s in TaskStatus]


def register_tasks_page(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retry_callback: Callable[[int], Any] | None = None,
    cancel_callback: Callable[[int], Any] | None = None,
) -> None:
    """Build the tasks page UI inside the current NiceGUI page context."""

    current_filter = {"value": "all"}
    task_container = ui.element("div").classes("w-full")

    async def _refresh() -> None:
        status_filter: TaskStatus | None = None
        if current_filter["value"] != "all":
            status_filter = TaskStatus(current_filter["value"])

        async with session_factory() as session:
            repo = Repository(session)
            tasks = await repo.list_tasks(status=status_filter, limit=100)

        task_container.clear()
        with task_container:
            if not tasks:
                ui.label(_("tasks.no_tasks")).classes("text-grey-6 py-4")
            else:
                with ui.column().classes("w-full gap-0"):
                    # Header row
                    with ui.row().classes("w-full items-center gap-4 py-2 px-4 bg-grey-2 text-xs font-bold"):
                        ui.label(_("tasks.header.id")).classes("w-12")
                        ui.label(_("tasks.header.video")).classes("flex-1")
                        ui.label(_("tasks.header.status")).classes("w-24")
                        ui.label(_("tasks.header.progress")).classes("w-40 text-center")
                        ui.label(_("tasks.header.attempt")).classes("w-20 text-center")
                        ui.label(_("tasks.header.actions")).classes("w-24")
                    for task in tasks:
                        render_task_row(
                            task,
                            on_retry=_on_retry,
                            on_cancel=_on_cancel,
                        )

    async def _on_retry(task_id: int) -> None:
        if retry_callback is not None:
            retry_callback(task_id)
        else:
            # Fallback: reset status to PENDING
            async with session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.PENDING, progress_pct=0.0)
                await repo.commit()
        log.info("task.retry_requested", task_id=task_id)
        ui.notify(_("tasks.retry_requested", task_id=str(task_id)), type="info")
        await _refresh()

    async def _on_cancel(task_id: int) -> None:
        if cancel_callback is not None:
            cancel_callback(task_id)
        else:
            async with session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.CANCELLED)
                await repo.commit()
        log.info("task.cancel_requested", task_id=task_id)
        ui.notify(_("tasks.cancel_requested", task_id=str(task_id)), type="warning")
        await _refresh()

    def _on_filter_change(e: Any) -> None:
        current_filter["value"] = e.value
        ui.timer(interval=0.01, callback=_refresh, once=True)

    # ── page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("tasks.title")).classes("text-2xl font-bold")
            with ui.row().classes("gap-2 items-center"):
                ui.select(
                    options=_FILTER_OPTIONS,
                    value="all",
                    label=_("tasks.filter.status"),
                    on_change=_on_filter_change,
                ).classes("w-40")
                ui.button(_("tasks.refresh"), icon="refresh", on_click=_refresh).props("flat")

        task_container  # noqa: B018

    # Auto-refresh every 5 seconds
    ui.timer(interval=5.0, callback=_refresh, once=False)
    ui.timer(interval=0.1, callback=_refresh, once=True)
