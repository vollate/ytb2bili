"""Dashboard page — overview stats and recent activity."""

from __future__ import annotations

import datetime
from typing import Any, Callable

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.core.models import Channel
from yt2bili.db.repository import Repository
from yt2bili.services.avatar import AvatarService

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def _relative_time(dt: datetime.datetime | None) -> str:
    """Return a human-friendly relative time string."""
    if dt is None:
        return _("channels.card.never_checked")
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


async def _load_stats(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Gather dashboard statistics from the database."""
    async with session_factory() as session:
        repo = Repository(session)
        channels = await repo.list_channels()
        all_tasks = await repo.list_tasks(limit=10000)
        recent_tasks = await repo.list_tasks(limit=10)

        active_statuses = {
            TaskStatus.DOWNLOADING,
            TaskStatus.UPLOADING,
            TaskStatus.SUBTITLING,
            TaskStatus.PENDING,
        }
        active_count = sum(1 for t in all_tasks if t.status in active_statuses)
        completed_count = sum(
            1 for t in all_tasks if t.status == TaskStatus.COMPLETED
        )
        total_videos = sum(len(ch.videos) for ch in channels if ch.videos)

        # Recent channels: sorted by last_checked_at descending, top 5
        checked_channels = sorted(
            [ch for ch in channels if ch.last_checked_at is not None],
            key=lambda c: c.last_checked_at,  # type: ignore[arg-type]
            reverse=True,
        )[:5]

        return {
            "total_channels": len(channels),
            "total_videos": total_videos,
            "active_tasks": active_count,
            "completed_today": completed_count,
            "recent_tasks": list(recent_tasks),
            "recent_channels": checked_channels,
        }


def register_dashboard_page(
    session_factory: async_sessionmaker[AsyncSession],
    check_all_callback: Callable[[], Any] | None = None,
    avatar_service: AvatarService | None = None,
) -> None:
    """Build the dashboard UI inside the current NiceGUI page context."""

    stats_container = ui.element("div").classes("w-full")
    recent_channels_container = ui.element("div").classes("w-full")
    activity_container = ui.element("div").classes("w-full")

    async def refresh() -> None:
        stats = await _load_stats(session_factory)

        stats_container.clear()
        with stats_container:
            with ui.row().classes("w-full gap-4 flex-wrap"):
                _stat_card(
                    _("dashboard.stats.channels"),
                    str(stats["total_channels"]),
                    icon="subscriptions",
                    color="blue",
                )
                _stat_card(
                    _("dashboard.stats.videos"),
                    str(stats["total_videos"]),
                    icon="video_library",
                    color="purple",
                )
                _stat_card(
                    _("dashboard.stats.active_tasks"),
                    str(stats["active_tasks"]),
                    icon="pending_actions",
                    color="orange",
                )
                _stat_card(
                    _("dashboard.stats.completed"),
                    str(stats["completed_today"]),
                    icon="check_circle",
                    color="green",
                )

        # Recent channels section
        recent_channels_container.clear()
        with recent_channels_container:
            ui.label(_("dashboard.recent_channels")).classes("text-lg font-bold mt-6 mb-2")
            recent_channels: list[Channel] = stats["recent_channels"]
            if not recent_channels:
                ui.label(_("dashboard.no_channels_checked")).classes("text-grey-6")
            else:
                with ui.column().classes("w-full gap-0"):
                    for ch in recent_channels:
                        with ui.row().classes(
                            "w-full items-center gap-3 py-2 border-b"
                        ):
                            avatar_url: str | None = None
                            if avatar_service is not None:
                                cached = avatar_service.get_cached_path(ch.youtube_channel_id)
                                if cached is not None:
                                    avatar_url = f"/avatars/{ch.youtube_channel_id}.jpg"
                            if avatar_url:
                                ui.image(avatar_url).classes(
                                    "w-8 h-8 rounded-full"
                                )
                            else:
                                ui.icon("account_circle", size="sm").classes(
                                    "text-grey-5"
                                )
                            ui.label(ch.name).classes("text-sm font-medium flex-1")
                            if ch.enabled:
                                ui.badge(_("channels.card.enabled"), color="green").props("dense")
                            else:
                                ui.badge(_("channels.card.disabled"), color="grey").props("dense")
                            ui.label(
                                _relative_time(ch.last_checked_at)
                            ).classes("text-xs text-grey-6")

        activity_container.clear()
        with activity_container:
            ui.label(_("dashboard.recent_activity")).classes("text-lg font-bold mt-6 mb-2")
            if not stats["recent_tasks"]:
                ui.label(_("dashboard.no_tasks")).classes("text-grey-6")
            else:
                with ui.column().classes("w-full gap-0"):
                    for task in stats["recent_tasks"]:
                        _activity_row(task)

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("dashboard.title")).classes("text-2xl font-bold")
            with ui.row().classes("gap-2"):
                ui.button(_("dashboard.refresh"), icon="refresh", on_click=refresh).props("flat")
                if check_all_callback is not None:
                    ui.button(
                        _("dashboard.check_all"), icon="sync", on_click=check_all_callback
                    ).props("color=primary")

        stats_container  # noqa: B018 — already bound above
        recent_channels_container  # noqa: B018
        activity_container  # noqa: B018

    ui.timer(interval=30.0, callback=refresh, once=False)
    ui.timer(interval=0.1, callback=refresh, once=True)  # initial load


def _stat_card(title: str, value: str, *, icon: str, color: str) -> None:
    with ui.card().classes("min-w-[180px] flex-1"):
        with ui.row().classes("items-center gap-3"):
            ui.icon(icon, size="sm", color=color)
            with ui.column().classes("gap-0"):
                ui.label(value).classes("text-2xl font-bold")
                ui.label(title).classes("text-xs text-grey-6")


def _activity_row(task: Any) -> None:
    status: TaskStatus = task.status
    video_title: str = (
        task.video.title
        if hasattr(task, "video") and task.video
        else f"Video #{task.video_id}"
    )
    with ui.row().classes("w-full items-center gap-4 py-1 border-b"):
        ui.label(f"#{task.id}").classes("text-xs font-mono w-10")
        ui.label(video_title).classes("text-sm flex-1 truncate")
        ui.badge(status.value).classes("text-xs")
        if task.updated_at:
            ui.label(f"{task.updated_at:%H:%M}").classes("text-xs text-grey-6")
