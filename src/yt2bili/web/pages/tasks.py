"""Tasks page — main landing page showing all pipeline tasks with status."""

from __future__ import annotations

import datetime
import math
from typing import Any, Callable

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.db.repository import Repository
from yt2bili.web.components.progress_bar import render_progress_bar

log: structlog.stdlib.BoundLogger = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────────────────

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

_ACTIVE_STATUSES = {TaskStatus.DOWNLOADING, TaskStatus.SUBTITLING, TaskStatus.UPLOADING}
_RETRYABLE_STATUSES = {TaskStatus.FAILED, TaskStatus.CANCELLED}
_CANCELLABLE_STATUSES = {TaskStatus.PENDING, TaskStatus.DOWNLOADING, TaskStatus.UPLOADING, TaskStatus.SUBTITLING}

# Filter tab → set of statuses
_FILTER_MAP: dict[str, set[TaskStatus] | None] = {
    "all": None,
    "active": _ACTIVE_STATUSES,
    "pending": {TaskStatus.PENDING},
    "completed": {TaskStatus.COMPLETED},
    "failed": {TaskStatus.FAILED, TaskStatus.CANCELLED},
}

_SORT_OPTIONS = {
    "latest": "tasks.sort.latest",
    "title": "tasks.sort.title",
    "added": "tasks.sort.added",
}

_VIEW_ICONS = {
    "list": "view_list",
    "grid": "grid_view",
    "table": "table_chart",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _relative_time(dt: datetime.datetime | None) -> str:
    if dt is None:
        return _("tasks.never")
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


def _fmt_speed(bps: float | None) -> str:
    if bps is None or bps <= 0:
        return "—"
    if bps >= 1_048_576:
        return f"{bps / 1_048_576:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


def _fmt_eta(seconds: int | float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}:{s:02d}"
    return f"{s}s"


def _video_title(task: Any) -> str:
    if hasattr(task, "video") and task.video:
        return task.video.title
    return f"Video #{task.video_id}"


def _video_thumbnail(task: Any) -> str | None:
    if hasattr(task, "video") and task.video and task.video.thumbnail_url:
        return task.video.thumbnail_url
    return None


def _channel_name(task: Any) -> str:
    if hasattr(task, "video") and task.video:
        if hasattr(task.video, "channel") and task.video.channel:
            return task.video.channel.name
        return f"Channel #{task.video.channel_id}"
    return ""


def _video_date(task: Any) -> str:
    if hasattr(task, "video") and task.video and task.video.youtube_upload_date:
        return f"{task.video.youtube_upload_date:%Y-%m-%d}"
    return ""


def _status_label(task: Any) -> str:
    """Human-readable status label with i18n."""
    key = f"tasks.{task.status.value}"
    return _(key)


# ── Main page ────────────────────────────────────────────────────────────────


def register_tasks_page(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    check_all_callback: Callable[[], Any] | None = None,
    retry_callback: Callable[[int], Any] | None = None,
    cancel_callback: Callable[[int], Any] | None = None,
    scheduler: Any | None = None,
    download_stats: dict[int, dict] | None = None,
    config: Any | None = None,
) -> None:
    """Build the Tasks page UI inside the current NiceGUI page context."""

    _containers: dict[str, Any] = {}

    # ── State ────────────────────────────────────────────────────────────
    _filter_tab: dict[str, str] = {"value": "all"}
    _search: dict[str, str] = {"value": ""}
    _sort_by: dict[str, str] = {"value": "latest"}
    _view_mode: dict[str, str] = {"value": "list"}
    _select_mode: dict[str, bool] = {"value": False}
    _selected_ids: set[int] = set()
    _page: dict[str, int] = {"value": 1}
    _page_size: dict[str, int] = {"value": 20}
    _total_count: dict[str, int] = {"value": 0}
    _current_tasks: list[Any] = []
    # Track which accordion item is expanded (by task id), only one at a time
    _expanded_id: dict[str, int | None] = {"value": None}
    # Status tab counts
    _tab_counts: dict[str, int] = {"all": 0, "active": 0, "pending": 0, "completed": 0, "failed": 0}

    # ── Callbacks ────────────────────────────────────────────────────────

    async def _on_retry(task_id: int) -> None:
        if retry_callback is not None:
            result = retry_callback(task_id)
            if hasattr(result, "__await__"):
                await result
        else:
            async with session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.PENDING, progress_pct=0.0)
                await repo.commit()
        ui.notify(_("tasks.retry_requested", task_id=str(task_id)), type="info")
        await _refresh()

    async def _on_cancel(task_id: int) -> None:
        if cancel_callback is not None:
            result = cancel_callback(task_id)
            if hasattr(result, "__await__"):
                await result
        else:
            async with session_factory() as session:
                repo = Repository(session)
                await repo.update_task_status(task_id, TaskStatus.CANCELLED)
                await repo.commit()
        ui.notify(_("tasks.cancel_requested", task_id=str(task_id)), type="warning")
        await _refresh()

    async def _on_check_now() -> None:
        if check_all_callback is not None:
            result = check_all_callback()
            if hasattr(result, "__await__"):
                await result
        await _refresh()

    async def _on_pause_resume() -> None:
        if scheduler is None:
            return
        if scheduler.running:
            scheduler.stop()
        else:
            scheduler.start()
        await _refresh()

    async def _batch_retry() -> None:
        for task in _current_tasks:
            if task.id in _selected_ids and task.status in _RETRYABLE_STATUSES:
                await _on_retry(task.id)

    async def _batch_cancel() -> None:
        for task in _current_tasks:
            if task.id in _selected_ids and task.status in _CANCELLABLE_STATUSES:
                await _on_cancel(task.id)

    def _toggle_select(task_id: int, selected: bool) -> None:
        if selected:
            _selected_ids.add(task_id)
        else:
            _selected_ids.discard(task_id)

    def _set_filter(tab: str) -> None:
        _filter_tab["value"] = tab
        _page["value"] = 1
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _set_sort(val: str) -> None:
        _sort_by["value"] = val or "latest"
        _page["value"] = 1
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _set_view(mode: str) -> None:
        _view_mode["value"] = mode
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _toggle_select_mode() -> None:
        _select_mode["value"] = not _select_mode["value"]
        if not _select_mode["value"]:
            _selected_ids.clear()
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _on_search_change(e: Any) -> None:
        _search["value"] = e.args or ""
        _page["value"] = 1
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _set_page_size(size: int) -> None:
        _page_size["value"] = size
        _page["value"] = 1
        ui.timer(interval=0.01, callback=_refresh, once=True)

    def _prev_page() -> None:
        if _page["value"] > 1:
            _page["value"] -= 1
            ui.timer(interval=0.01, callback=_refresh, once=True)

    def _next_page() -> None:
        total_pages = max(1, math.ceil(_total_count["value"] / _page_size["value"]))
        if _page["value"] < total_pages:
            _page["value"] += 1
            ui.timer(interval=0.01, callback=_refresh, once=True)

    def _toggle_expand(task_id: int) -> None:
        if _expanded_id["value"] == task_id:
            _expanded_id["value"] = None
        else:
            _expanded_id["value"] = task_id
        ui.timer(interval=0.01, callback=_refresh, once=True)

    # ── Data loading ─────────────────────────────────────────────────────

    async def _load_counts() -> dict[str, int]:
        """Load counts for each filter tab."""
        async with session_factory() as session:
            repo = Repository(session)
            all_tasks = await repo.list_tasks(limit=100000)

        counts: dict[str, int] = {"all": 0, "active": 0, "pending": 0, "completed": 0, "failed": 0}
        for t in all_tasks:
            counts["all"] += 1
            if t.status in _ACTIVE_STATUSES:
                counts["active"] += 1
            elif t.status == TaskStatus.PENDING:
                counts["pending"] += 1
            elif t.status == TaskStatus.COMPLETED:
                counts["completed"] += 1
            elif t.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                counts["failed"] += 1
        return counts

    async def _load_tasks() -> tuple[list[Any], int]:
        """Load tasks for the current page with filters."""
        filter_statuses = _FILTER_MAP.get(_filter_tab["value"])

        async with session_factory() as session:
            repo = Repository(session)

            # For simplicity, we load all tasks with the filter and paginate in Python
            # since the repository doesn't have a dedicated task listing with all these filters
            all_tasks = await repo.list_tasks(limit=100000)

        # Apply status filter
        if filter_statuses is not None:
            all_tasks = [t for t in all_tasks if t.status in filter_statuses]

        # Apply search filter
        search = _search["value"].strip().lower()
        if search:
            all_tasks = [t for t in all_tasks if search in _video_title(t).lower()]

        # Sort
        sort = _sort_by["value"]
        if sort == "title":
            all_tasks = sorted(all_tasks, key=lambda t: _video_title(t).lower())
        elif sort == "added":
            all_tasks = sorted(all_tasks, key=lambda t: t.created_at or datetime.datetime.min, reverse=True)
        else:  # latest — by updated_at desc
            all_tasks = sorted(all_tasks, key=lambda t: t.updated_at or t.created_at or datetime.datetime.min, reverse=True)

        total = len(all_tasks)

        # Paginate
        offset = (_page["value"] - 1) * _page_size["value"]
        page_tasks = list(all_tasks[offset : offset + _page_size["value"]])

        return page_tasks, total

    # ── Refresh ──────────────────────────────────────────────────────────

    async def _refresh() -> None:
        # Load counts
        counts = await _load_counts()
        _tab_counts.update(counts)

        # Load tasks
        tasks, total = await _load_tasks()
        _current_tasks.clear()
        _current_tasks.extend(tasks)
        _total_count["value"] = total

        # Clean up selected IDs
        current_ids = {t.id for t in tasks}
        _selected_ids.intersection_update(current_ids)

        # ── Summary Bar ──────────────────────────────────────────────
        _containers["summary"].clear()
        with _containers["summary"]:
            _render_summary_bar()

        # ── Filter Tabs ──────────────────────────────────────────────
        _containers["filters"].clear()
        with _containers["filters"]:
            _render_filter_tabs()

        # ── Batch bar ────────────────────────────────────────────────
        _containers["batch_bar"].clear()
        if _select_mode["value"] and _selected_ids:
            with _containers["batch_bar"]:
                _render_batch_bar()

        # ── Task list ────────────────────────────────────────────────
        _containers["task_list"].clear()
        with _containers["task_list"]:
            if not tasks:
                ui.label(_("tasks.no_tasks")).classes("text-grey-6 py-8 text-center")
            else:
                mode = _view_mode["value"]
                if mode == "grid":
                    _render_grid_view(tasks)
                elif mode == "table":
                    _render_table_view(tasks)
                else:
                    _render_list_view(tasks)

        # ── Pagination ───────────────────────────────────────────────
        _containers["pagination"].clear()
        with _containers["pagination"]:
            _render_pagination()

    # ── Summary Bar ──────────────────────────────────────────────────────

    def _render_summary_bar() -> None:
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between flex-wrap gap-3"):
                # Left side: scheduler info + pipeline counts
                with ui.row().classes("items-center gap-4 flex-wrap"):
                    # Scheduler status
                    with ui.row().classes("items-center gap-2"):
                        ui.label(_("tasks.summary.scheduler_label") + ":").classes("text-sm font-medium")
                        if scheduler is not None and scheduler.running:
                            ui.badge(_("tasks.summary.scheduler_running"), color="green").props("dense")
                            if config and hasattr(config, "schedule"):
                                interval = config.schedule.poll_interval_minutes
                                ui.label(
                                    _("tasks.summary.every_n_min", minutes=str(interval))
                                ).classes("text-xs text-grey-6")
                        else:
                            ui.badge(_("tasks.summary.scheduler_stopped"), color="red").props("dense")

                    ui.separator().props("vertical").classes("h-6")

                    # Last check time
                    if scheduler is not None:
                        last_check = getattr(scheduler, "last_check_time", None)
                        ui.label(
                            _("tasks.summary.last_check", time=_relative_time(last_check))
                        ).classes("text-sm text-grey-7")

                    ui.separator().props("vertical").classes("h-6")

                    # Pipeline counts
                    dl_count = _tab_counts.get("active", 0)
                    # Break down active into downloading/uploading from current data
                    dl_n = sum(1 for t in _current_tasks if t.status == TaskStatus.DOWNLOADING)
                    ul_n = sum(1 for t in _current_tasks if t.status == TaskStatus.UPLOADING)
                    pend_n = _tab_counts.get("pending", 0)
                    ui.label(
                        _("tasks.summary.pipeline",
                          downloading=str(dl_n),
                          uploading=str(ul_n),
                          pending=str(pend_n))
                    ).classes("text-sm text-grey-7")

                # Right side: action buttons
                with ui.row().classes("gap-2"):
                    if check_all_callback is not None:
                        ui.button(
                            _("tasks.summary.check_now"),
                            icon="sync",
                            on_click=_on_check_now,
                        ).props("dense outline")
                    if scheduler is not None:
                        if scheduler.running:
                            ui.button(
                                _("tasks.summary.pause"),
                                icon="pause",
                                on_click=_on_pause_resume,
                            ).props("dense outline")
                        else:
                            ui.button(
                                _("tasks.summary.resume"),
                                icon="play_arrow",
                                on_click=_on_pause_resume,
                            ).props("dense outline color=green")

    # ── Filter Tabs ──────────────────────────────────────────────────────

    def _render_filter_tabs() -> None:
        with ui.row().classes("gap-1 flex-wrap"):
            for tab_key, label_key in [
                ("all", "tasks.filter.all"),
                ("active", "tasks.filter.active"),
                ("pending", "tasks.filter.pending"),
                ("completed", "tasks.filter.completed"),
                ("failed", "tasks.filter.failed"),
            ]:
                count = _tab_counts.get(tab_key, 0)
                is_active = _filter_tab["value"] == tab_key
                label = f"{_(label_key)} {count}"
                btn = ui.button(label, on_click=lambda _, k=tab_key: _set_filter(k))
                if is_active:
                    btn.props("color=primary dense")
                else:
                    btn.props("flat dense")

    # ── Batch Bar ────────────────────────────────────────────────────────

    def _render_batch_bar() -> None:
        with ui.row().classes("w-full items-center gap-3 py-2 px-4 bg-blue-1 rounded"):
            ui.label(
                _("tasks.batch.selected_count", count=str(len(_selected_ids)))
            ).classes("text-sm font-medium")

            if retry_callback is not None:
                ui.button(
                    _("tasks.batch.retry_selected"),
                    icon="replay",
                    on_click=_batch_retry,
                ).props("flat dense color=primary")

            if cancel_callback is not None:
                ui.button(
                    _("tasks.batch.cancel_selected"),
                    icon="cancel",
                    on_click=_batch_cancel,
                ).props("flat dense color=negative")

    # ── List View ────────────────────────────────────────────────────────

    def _render_list_view(tasks: list[Any]) -> None:
        with ui.column().classes("w-full gap-0"):
            for task in tasks:
                _render_list_item(task)

    def _render_list_item(task: Any) -> None:
        color = _STATUS_COLORS.get(task.status.value, "grey")
        is_expanded = _expanded_id["value"] == task.id
        title = _video_title(task)
        thumb = _video_thumbnail(task)
        ch_name = _channel_name(task)
        date = _video_date(task)
        stats = download_stats.get(task.id, {}) if download_stats and task.status == TaskStatus.DOWNLOADING else {}

        with ui.card().classes("w-full mb-1").props("flat bordered"):
            # Main row — clickable to expand
            with ui.row().classes("w-full items-center gap-3 py-2 px-3 cursor-pointer").on(
                "click", lambda _, tid=task.id: _toggle_expand(tid)
            ):
                # Select checkbox (only in select mode)
                if _select_mode["value"]:
                    is_selected = task.id in _selected_ids
                    cb = ui.checkbox(value=is_selected).props("dense size=xs")
                    cb.on("update:model-value", lambda e, tid=task.id: _toggle_select(tid, e.args))
                    # Stop click propagation so checkbox doesn't trigger expand
                    cb.on("click", lambda e: e.args, [], propagate=False) if False else None

                # Thumbnail
                if thumb:
                    ui.image(thumb).classes("w-20 h-12 rounded object-cover flex-shrink-0")
                else:
                    ui.icon("movie", size="md").classes("w-20 text-center text-grey-4 flex-shrink-0")

                # Title + channel · date
                with ui.column().classes("flex-1 gap-0 min-w-0"):
                    ui.label(title).classes("text-sm font-medium truncate")
                    with ui.row().classes("gap-2 text-xs text-grey-6"):
                        if ch_name:
                            ui.label(ch_name)
                        if date:
                            ui.label(f"· {date}")

                # Status + progress
                with ui.column().classes("items-end gap-1 flex-shrink-0"):
                    # Status badge with icon
                    if task.status == TaskStatus.DOWNLOADING:
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("download", size="xs", color=color)
                            ui.label(f"{_status_label(task)} {task.progress_pct:.0f}%").classes("text-xs")
                    elif task.status == TaskStatus.UPLOADING:
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("upload", size="xs", color=color)
                            ui.label(f"{_status_label(task)} {task.progress_pct:.0f}%").classes("text-xs")
                    elif task.status == TaskStatus.COMPLETED:
                        ui.badge(_status_label(task), color=color).props("dense")
                    elif task.status == TaskStatus.FAILED:
                        with ui.row().classes("items-center gap-1"):
                            ui.badge(_status_label(task), color=color).props("dense")
                            ui.button(
                                _("tasks.retry"),
                                icon="replay",
                                on_click=lambda _, tid=task.id: _on_retry(tid),
                            ).props("flat dense size=xs color=primary")
                    else:
                        ui.badge(_status_label(task), color=color).props("dense")

                # Progress bar for active tasks
                if task.status in _ACTIVE_STATUSES:
                    with ui.element("div").classes("w-full"):
                        render_progress_bar(task.progress_pct, color=color, size="6px")
                        if task.status == TaskStatus.DOWNLOADING and stats:
                            with ui.row().classes("gap-3 text-xs text-grey-6 mt-1"):
                                ui.label(f"{_fmt_speed(stats.get('speed'))} · ETA {_fmt_eta(stats.get('eta'))}")

            # Expanded detail (accordion)
            if is_expanded:
                with ui.column().classes("w-full px-4 pb-3 pt-1 border-t gap-2"):
                    _render_task_detail(task)

    # ── Grid View ────────────────────────────────────────────────────────

    def _render_grid_view(tasks: list[Any]) -> None:
        with ui.element("div").classes(
            "w-full grid gap-3"
        ).style("grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))"):
            for task in tasks:
                _render_grid_card(task)

    def _render_grid_card(task: Any) -> None:
        color = _STATUS_COLORS.get(task.status.value, "grey")
        title = _video_title(task)
        thumb = _video_thumbnail(task)
        ch_name = _channel_name(task)

        with ui.card().classes("w-full cursor-pointer").on(
            "click", lambda _, tid=task.id: _open_detail_dialog(tid)
        ):
            # Thumbnail
            if thumb:
                ui.image(thumb).classes("w-full h-32 rounded object-cover")
            else:
                with ui.element("div").classes("w-full h-32 bg-grey-2 rounded flex items-center justify-center"):
                    ui.icon("movie", size="xl").classes("text-grey-4")

            # Title
            ui.label(title).classes("text-sm font-medium truncate mt-2")

            # Channel
            if ch_name:
                ui.label(ch_name).classes("text-xs text-grey-6 truncate")

            # Status badge
            with ui.row().classes("items-center gap-2 mt-1"):
                ui.badge(_status_label(task), color=color).props("dense")
                if task.status in _ACTIVE_STATUSES:
                    ui.label(f"{task.progress_pct:.0f}%").classes("text-xs text-grey-6")

            # Progress bar for active
            if task.status in _ACTIVE_STATUSES:
                render_progress_bar(task.progress_pct, color=color, size="4px")

            # Select checkbox
            if _select_mode["value"]:
                is_selected = task.id in _selected_ids
                cb = ui.checkbox(value=is_selected).props("dense size=xs").classes("absolute top-2 left-2")
                cb.on("update:model-value", lambda e, tid=task.id: _toggle_select(tid, e.args))

    def _open_detail_dialog(task_id: int) -> None:
        task = next((t for t in _current_tasks if t.id == task_id), None)
        if task is None:
            return
        with ui.dialog() as dlg, ui.card().classes("w-[600px] max-h-[80vh]"):
            _render_task_detail(task)
            with ui.row().classes("w-full justify-end mt-4"):
                ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
        dlg.open()

    # ── Table View ───────────────────────────────────────────────────────

    def _render_table_view(tasks: list[Any]) -> None:
        columns = [
            {"name": "title", "label": _("tasks.name"), "field": "title", "align": "left", "sortable": True},
            {"name": "channel", "label": _("tasks.channel"), "field": "channel", "align": "left"},
            {"name": "status", "label": _("tasks.status"), "field": "status", "align": "center"},
            {"name": "progress", "label": _("tasks.progress"), "field": "progress", "align": "right"},
            {"name": "speed", "label": _("tasks.speed"), "field": "speed", "align": "right"},
            {"name": "eta", "label": _("tasks.eta"), "field": "eta", "align": "right"},
            {"name": "added", "label": _("tasks.added"), "field": "added", "align": "right"},
        ]

        rows = []
        for task in tasks:
            stats = download_stats.get(task.id, {}) if download_stats and task.status == TaskStatus.DOWNLOADING else {}
            rows.append({
                "id": task.id,
                "title": _video_title(task),
                "channel": _channel_name(task),
                "status": _status_label(task),
                "progress": f"{task.progress_pct:.0f}%" if task.progress_pct else "—",
                "speed": _fmt_speed(stats.get("speed")) if stats else "—",
                "eta": _fmt_eta(stats.get("eta")) if stats else "—",
                "added": f"{task.created_at:%Y-%m-%d %H:%M}" if task.created_at else "—",
            })

        table = ui.table(
            columns=columns,
            rows=rows,
            row_key="id",
            selection="multiple" if _select_mode["value"] else None,
        ).classes("w-full")
        table.props("flat bordered dense")

        # Handle row click for expansion
        def _on_row_click(e: Any) -> None:
            row = e.args.get("row") if isinstance(e.args, dict) else None
            if row and "id" in row:
                _toggle_expand(row["id"])

        table.on("row-click", _on_row_click)

        # Show expanded detail below table if any
        if _expanded_id["value"] is not None:
            expanded_task = next((t for t in tasks if t.id == _expanded_id["value"]), None)
            if expanded_task:
                with ui.card().classes("w-full mt-2").props("flat bordered"):
                    with ui.column().classes("p-4"):
                        _render_task_detail(expanded_task)

    # ── Task Detail (shared by all views) ────────────────────────────────

    def _render_task_detail(task: Any) -> None:
        """Render full detail for a task."""
        title = _video_title(task)
        thumb = _video_thumbnail(task)
        ch_name = _channel_name(task)
        color = _STATUS_COLORS.get(task.status.value, "grey")
        stats = download_stats.get(task.id, {}) if download_stats and task.status == TaskStatus.DOWNLOADING else {}

        with ui.row().classes("w-full gap-4"):
            # Large thumbnail
            if thumb:
                ui.image(thumb).classes("w-48 h-28 rounded object-cover flex-shrink-0")

            with ui.column().classes("flex-1 gap-2"):
                ui.label(title).classes("text-base font-bold")
                with ui.row().classes("gap-4 text-sm text-grey-7"):
                    if ch_name:
                        ui.label(ch_name)
                    date = _video_date(task)
                    if date:
                        ui.label(date)

                # Status + progress
                with ui.row().classes("items-center gap-3"):
                    ui.badge(_status_label(task), color=color)
                    ui.label(_("tasks.attempt", attempt=str(task.attempt))).classes("text-xs text-grey-6")

                if task.status in _ACTIVE_STATUSES:
                    with ui.row().classes("w-full items-center gap-2"):
                        with ui.element("div").classes("flex-1"):
                            render_progress_bar(task.progress_pct, color=color, size="16px")
                        ui.label(f"{task.progress_pct:.0f}%").classes("text-sm font-mono")
                    if stats:
                        with ui.row().classes("gap-4 text-xs text-grey-6"):
                            ui.label(f"{_('tasks.speed')}: {_fmt_speed(stats.get('speed'))}")
                            ui.label(f"{_('tasks.eta')}: {_fmt_eta(stats.get('eta'))}")

                # Error message
                if task.error_message:
                    with ui.card().classes("w-full bg-red-1").props("flat"):
                        ui.label(task.error_message).classes("text-xs text-red whitespace-pre-wrap")

                # Description
                if hasattr(task, "video") and task.video and task.video.description:
                    with ui.expansion(_("tasks.description"), icon="description").classes("w-full text-sm"):
                        ui.label(task.video.description).classes("text-xs text-grey-7 whitespace-pre-wrap")

                # Links
                with ui.row().classes("gap-2"):
                    if hasattr(task, "video") and task.video:
                        yt_url = f"https://www.youtube.com/watch?v={task.video.youtube_id}"
                        ui.button(
                            _("tasks.youtube_link"),
                            icon="open_in_new",
                            on_click=lambda _, u=yt_url: ui.navigate.to(u, new_tab=True),
                        ).props("flat dense size=sm")
                    if hasattr(task, "bilibili_bvid") and task.bilibili_bvid:
                        bili_url = f"https://www.bilibili.com/video/{task.bilibili_bvid}"
                        ui.button(
                            _("tasks.bilibili_link"),
                            icon="open_in_new",
                            on_click=lambda _, u=bili_url: ui.navigate.to(u, new_tab=True),
                        ).props("flat dense size=sm")

                # Action buttons
                with ui.row().classes("gap-2 mt-1"):
                    if task.status in _RETRYABLE_STATUSES:
                        ui.button(
                            _("tasks.retry"),
                            icon="replay",
                            on_click=lambda _, tid=task.id: _on_retry(tid),
                        ).props("dense color=primary")
                    if task.status in _CANCELLABLE_STATUSES:
                        ui.button(
                            _("tasks.cancel"),
                            icon="cancel",
                            on_click=lambda _, tid=task.id: _on_cancel(tid),
                        ).props("dense color=negative")

    # ── Pagination ───────────────────────────────────────────────────────

    def _render_pagination() -> None:
        total_pages = max(1, math.ceil(_total_count["value"] / _page_size["value"]))
        if total_pages <= 1:
            return
        with ui.row().classes("w-full justify-center items-center gap-3 py-3"):
            ui.button(icon="chevron_left", on_click=_prev_page).props(
                "flat dense round"
            ).set_enabled(_page["value"] > 1)
            ui.label(
                _("tasks.page_info", page=str(_page["value"]), total=str(total_pages))
            ).classes("text-sm")
            ui.button(icon="chevron_right", on_click=_next_page).props(
                "flat dense round"
            ).set_enabled(_page["value"] < total_pages)

            ui.select(
                {10: "10", 20: "20", 50: "50"},
                value=_page_size["value"],
                label=_("tasks.per_page"),
                on_change=lambda e: _set_page_size(e.value),
            ).classes("w-24").props("dense outlined")

    # ── Page Layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4 max-w-6xl mx-auto"):
        # Summary bar
        _containers["summary"] = ui.element("div").classes("w-full")

        # Filter tabs
        _containers["filters"] = ui.element("div").classes("w-full")

        # Toolbar: search + sort + view + select
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            search_input = ui.input(
                placeholder=_("tasks.search_placeholder"),
            ).classes("flex-1 min-w-[200px]").props("dense outlined clearable")
            search_input.on("update:model-value", _on_search_change)

            sort_options = {k: _(v) for k, v in _SORT_OPTIONS.items()}
            ui.select(
                sort_options,
                value="latest",
                on_change=lambda e: _set_sort(e.value),
            ).classes("w-36").props("dense outlined").props('label="Sort"')

            # View mode dropdown
            with ui.button(icon=_VIEW_ICONS[_view_mode["value"]]).props("flat dense"):
                with ui.menu():
                    for mode, icon in _VIEW_ICONS.items():
                        label_key = f"tasks.view.{mode}"
                        ui.menu_item(
                            _(label_key),
                            on_click=lambda _, m=mode: _set_view(m),
                        ).props(f'icon="{icon}"')

            # Select mode toggle
            select_btn = ui.button(
                _("tasks.select"),
                icon="check_box_outline_blank" if not _select_mode["value"] else "check_box",
                on_click=_toggle_select_mode,
            )
            if _select_mode["value"]:
                select_btn.props("dense color=primary")
            else:
                select_btn.props("dense flat")

        # Batch actions bar
        _containers["batch_bar"] = ui.element("div").classes("w-full")

        # Task list
        _containers["task_list"] = ui.element("div").classes("w-full")

        # Pagination
        _containers["pagination"] = ui.element("div").classes("w-full")

    # Auto-refresh
    ui.timer(interval=5.0, callback=_refresh, once=False)
    ui.timer(interval=0.1, callback=_refresh, once=True)
