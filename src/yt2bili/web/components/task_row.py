"""Reusable task-row component for NiceGUI."""

from __future__ import annotations

from typing import Any, Callable

from nicegui import ui

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.web.components.progress_bar import render_progress_bar

_STATUS_COLOR: dict[TaskStatus, str] = {
    TaskStatus.PENDING: "grey",
    TaskStatus.DOWNLOADING: "blue",
    TaskStatus.SUBTITLING: "purple",
    TaskStatus.UPLOADING: "orange",
    TaskStatus.COMPLETED: "positive",
    TaskStatus.FAILED: "negative",
    TaskStatus.RETRYING: "warning",
    TaskStatus.CANCELLED: "grey-6",
}


def render_task_row(
    task: Any,
    *,
    on_retry: Callable[[int], Any] | None = None,
    on_cancel: Callable[[int], Any] | None = None,
) -> None:
    """Render a single task row inside a table or card context.

    Parameters
    ----------
    task:
        An ORM ``Task`` object (or anything with the same attributes).
    on_retry:
        Callback invoked with *task.id* when the retry button is clicked.
    on_cancel:
        Callback invoked with *task.id* when the cancel button is clicked.
    """
    status: TaskStatus = task.status
    color = _STATUS_COLOR.get(status, "grey")
    video_title: str = task.video.title if hasattr(task, "video") and task.video else f"Video #{task.video_id}"

    with ui.row().classes("w-full items-center gap-4 py-2 px-4 border-b"):
        ui.label(f"#{task.id}").classes("text-sm font-mono w-12")
        ui.label(video_title).classes("text-sm flex-1 truncate")
        ui.badge(status.value, color=color).classes("text-xs")

        # Progress bar for active tasks
        if status in {TaskStatus.DOWNLOADING, TaskStatus.UPLOADING, TaskStatus.SUBTITLING}:
            with ui.element("div").classes("w-40"):
                render_progress_bar(task.progress_pct, color=color)
        else:
            ui.label(f"{task.progress_pct:.0f}%").classes("text-xs w-40 text-center")

        ui.label(_("tasks.attempt", attempt=str(task.attempt))).classes("text-xs w-20 text-center")

        # Action buttons
        with ui.row().classes("gap-1"):
            if status == TaskStatus.FAILED and on_retry is not None:
                ui.button(icon="replay", on_click=lambda _, tid=task.id: on_retry(tid)).props(
                    "flat dense round size=sm"
                ).tooltip(_("tasks.retry"))
            if status in {TaskStatus.PENDING, TaskStatus.DOWNLOADING, TaskStatus.UPLOADING} and on_cancel is not None:
                ui.button(icon="cancel", on_click=lambda _, tid=task.id: on_cancel(tid)).props(
                    "flat dense round size=sm color=negative"
                ).tooltip(_("tasks.cancel"))
