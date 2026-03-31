"""Reusable channel card component for NiceGUI."""

from __future__ import annotations

import datetime
from typing import Any, Callable

from nicegui import ui

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _


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
        mins = seconds // 60
        return f"{mins}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"


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


def render_channel_card(
    channel: Any,
    *,
    avatar_path: str | None = None,
    on_toggle: Callable[[int, bool], Any] | None = None,
    on_delete: Callable[[int], Any] | None = None,
    on_edit: Callable[[int], Any] | None = None,
    on_check: Callable[[int], Any] | None = None,
) -> None:
    """Render a card-style UI element for a single channel.

    Parameters
    ----------
    channel:
        An ORM ``Channel`` object.
    avatar_path:
        Optional path/URL to the channel avatar image.
    on_toggle:
        Callback ``(channel_id, new_enabled)`` when the toggle switch changes.
    on_delete:
        Callback ``(channel_id)`` when delete is confirmed.
    on_edit:
        Callback ``(channel_id)`` when the edit button is clicked.
    on_check:
        Callback ``(channel_id)`` when "Check Now" is clicked.
    """
    videos = channel.videos if hasattr(channel, "videos") and channel.videos else []
    video_count = len(videos)

    with ui.card().classes("w-full max-w-md"):
        # ── Top row: avatar + info + toggle ──────────────────────────────
        with ui.row().classes("w-full items-center gap-3"):
            # Avatar
            if avatar_path:
                ui.html(
                    f'<img src="{avatar_path}" style="width:48px;height:48px;border-radius:50%;object-fit:cover;" />'
                )
            else:
                ui.icon("account_circle", size="xl").classes("text-grey-5")

            # Name + ID + badges
            with ui.column().classes("flex-1 gap-0"):
                ui.label(channel.name).classes("text-lg font-bold")
                ui.label(channel.youtube_channel_id).classes(
                    "text-xs text-grey-6 font-mono"
                )
                with ui.row().classes("gap-2 mt-1"):
                    ui.badge(_("channels.card.videos", count=str(video_count)), color="blue").props("outline")
                    if channel.enabled:
                        ui.badge(_("channels.card.enabled"), color="green")
                    else:
                        ui.badge(_("channels.card.disabled"), color="grey")

            ui.switch(
                value=channel.enabled,
                on_change=lambda e, cid=channel.id: (
                    on_toggle(cid, e.value) if on_toggle else None
                ),
            ).tooltip(_("channels.card.enable_disable"))

        # ── Stats row ────────────────────────────────────────────────────
        with ui.row().classes("text-xs text-grey-6 gap-4"):
            last_checked = channel.last_checked_at
            ui.icon("schedule", size="xs")
            ui.label(_relative_time(last_checked))

        # ── Expandable recent videos ─────────────────────────────────────
        if videos:
            recent = sorted(videos, key=lambda v: v.created_at, reverse=True)[:5]
            with ui.expansion(_("channels.card.recent_videos"), icon="video_library").classes(
                "w-full text-sm"
            ):
                for video in recent:
                    with ui.row().classes("w-full items-center gap-2 py-1 border-b"):
                        ui.label(video.title).classes("flex-1 truncate text-xs")
                        if hasattr(video, "tasks") and video.tasks:
                            latest_task = max(video.tasks, key=lambda t: t.updated_at)
                            color = _STATUS_COLORS.get(latest_task.status.value, "grey")
                            ui.badge(latest_task.status.value, color=color).props(
                                "dense"
                            )

        # ── Action buttons ───────────────────────────────────────────────
        with ui.row().classes("w-full justify-end gap-1 mt-2"):
            if on_check is not None:
                ui.button(
                    _("channels.card.check_now"),
                    icon="sync",
                    on_click=lambda _, cid=channel.id: on_check(cid),
                ).props("flat dense size=sm")
            if on_edit is not None:
                ui.button(
                    icon="edit",
                    on_click=lambda _, cid=channel.id: on_edit(cid),
                ).props("flat dense round size=sm").tooltip(_("channels.card.edit"))
            if on_delete is not None:
                with ui.element("span"):
                    btn = ui.button(icon="delete", color="negative").props(
                        "flat dense round size=sm"
                    )
                    btn.tooltip(_("channels.card.delete"))
                    with ui.menu().props("auto-close"):
                        ui.menu_item(
                            _("channels.card.confirm_delete"),
                            on_click=lambda _, cid=channel.id: on_delete(cid),
                        )
                    btn.on("click", lambda: None)  # menu anchored to btn
