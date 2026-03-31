"""Videos listing page — browse all discovered videos with task status."""

from __future__ import annotations

import datetime
from typing import Any

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.db.repository import Repository

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_STATUS_COLORS: dict[str, str] = {
    TaskStatus.PENDING.value: "grey",
    TaskStatus.DOWNLOADING.value: "blue",
    TaskStatus.SUBTITLING.value: "purple",
    TaskStatus.UPLOADING.value: "orange",
    TaskStatus.COMPLETED.value: "green",
    TaskStatus.FAILED.value: "red",
    TaskStatus.RETRYING.value: "amber",
    TaskStatus.CANCELLED.value: "grey",
}


def _relative_time(dt: datetime.datetime | None) -> str:
    """Return a human-friendly relative time string."""
    if dt is None:
        return "—"
    now = datetime.datetime.now(tz=dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _overall_status(tasks: list[Any]) -> str:
    """Determine the overall status label from a video's tasks."""
    if not tasks:
        return "no tasks"
    statuses = {t.status for t in tasks}
    # Priority ordering: active states first
    for s in (
        TaskStatus.UPLOADING,
        TaskStatus.SUBTITLING,
        TaskStatus.DOWNLOADING,
        TaskStatus.PENDING,
        TaskStatus.RETRYING,
        TaskStatus.FAILED,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    ):
        if s in statuses:
            return s.value
    return "unknown"


def register_videos_page(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Build the videos listing UI inside the current NiceGUI page context."""

    video_list_container = ui.element("div").classes("w-full")

    # Filter state
    _filter_channel: dict[str, int | None] = {"value": None}
    _filter_status: dict[str, TaskStatus | None] = {"value": None}

    async def _load_channels() -> list[dict[str, Any]]:
        async with session_factory() as session:
            repo = Repository(session)
            channels = await repo.list_channels()
        return [{"id": ch.id, "name": ch.name} for ch in channels]

    async def _refresh() -> None:
        async with session_factory() as session:
            repo = Repository(session)
            videos = await repo.list_videos_with_tasks(
                channel_id=_filter_channel["value"],
                status=_filter_status["value"],
                limit=50,
            )

        video_list_container.clear()
        with video_list_container:
            if not videos:
                ui.label(_("videos.no_videos")).classes("text-grey-6 py-4")
                return

            for video in videos:
                tasks = list(video.tasks) if hasattr(video, "tasks") and video.tasks else []
                status_label = _overall_status(tasks)
                status_color = _STATUS_COLORS.get(status_label, "grey")
                channel_name = (
                    video.channel.name
                    if hasattr(video, "channel") and video.channel
                    else f"Channel #{video.channel_id}"
                )

                with ui.card().classes("w-full mb-2"):
                    with ui.row().classes("w-full items-center gap-4"):
                        # Thumbnail
                        if video.thumbnail_url:
                            ui.image(video.thumbnail_url).classes(
                                "w-24 h-16 rounded object-cover"
                            )
                        else:
                            ui.icon("movie", size="lg").classes(
                                "w-24 text-center text-grey-5"
                            )

                        # Info columns
                        with ui.column().classes("flex-1 gap-0"):
                            ui.label(video.title).classes("text-sm font-medium truncate")
                            with ui.row().classes("gap-3 text-xs text-grey-6"):
                                ui.label(channel_name)
                                upload_date = video.youtube_upload_date
                                if upload_date:
                                    ui.label(f"{upload_date:%Y-%m-%d}")
                                else:
                                    ui.label(_relative_time(video.created_at))

                        # Status badge
                        ui.badge(status_label, color=status_color)

                    # Expandable detail
                    with ui.expansion(_("videos.details"), icon="info").classes(
                        "w-full text-xs"
                    ):
                        with ui.column().classes("gap-2 py-2"):
                            if video.description:
                                ui.label(video.description[:500]).classes(
                                    "text-xs text-grey-7 whitespace-pre-wrap"
                                )

                            yt_url = f"https://www.youtube.com/watch?v={video.youtube_id}"
                            ui.link(_("videos.youtube_link"), yt_url, new_tab=True).classes(
                                "text-xs"
                            )

                            if tasks:
                                ui.label(_("videos.tasks_label")).classes("text-xs font-bold mt-2")
                                for task in tasks:
                                    t_color = _STATUS_COLORS.get(
                                        task.status.value, "grey"
                                    )
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(f"#{task.id}").classes(
                                            "text-xs font-mono"
                                        )
                                        ui.badge(
                                            task.status.value, color=t_color
                                        ).props("dense")
                                        if task.progress_pct > 0:
                                            ui.label(
                                                f"{task.progress_pct:.0f}%"
                                            ).classes("text-xs")
                                        if task.error_message:
                                            ui.label(
                                                task.error_message[:100]
                                            ).classes("text-xs text-red")

    # ── page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("videos.title")).classes("text-2xl font-bold")
            ui.button(_("common.refresh"), icon="refresh", on_click=_refresh).props("flat")

        # Filter row
        with ui.row().classes("w-full items-center gap-4"):
            # Channel filter — populated async
            channel_select = ui.select(
                {},
                value=None,
                label=_("videos.filter.all_channels"),
                clearable=True,
            ).classes("w-56").props("dense outlined")

            async def _populate_channels() -> None:
                channel_list = await _load_channels()
                options: dict[int | None, str] = {}
                for ch in channel_list:
                    options[ch["id"]] = ch["name"]
                channel_select.options = options  # type: ignore[assignment]
                channel_select.update()

            def _on_channel_change(e: Any) -> None:
                _filter_channel["value"] = e.value

            channel_select.on("update:model-value", _on_channel_change)
            channel_select.on(
                "update:model-value",
                lambda _: _refresh(),  # type: ignore[arg-type, return-value]
            )

            # Status filter
            status_options: dict[str | None, str] = {None: _("videos.filter.all")}
            for s in TaskStatus:
                status_options[s.value] = s.value.capitalize()
            status_select = ui.select(
                status_options,
                value=None,
                label=_("videos.filter.all_statuses"),
                clearable=True,
            ).classes("w-44").props("dense outlined")

            def _on_status_change(e: Any) -> None:
                val = e.value
                _filter_status["value"] = TaskStatus(val) if val else None

            status_select.on("update:model-value", _on_status_change)
            status_select.on(
                "update:model-value",
                lambda _: _refresh(),  # type: ignore[arg-type, return-value]
            )

        video_list_container  # noqa: B018

    # Auto-refresh every 10s + initial load
    ui.timer(interval=10.0, callback=_refresh, once=False)
    ui.timer(interval=0.1, callback=_populate_channels, once=True)
    ui.timer(interval=0.15, callback=_refresh, once=True)
