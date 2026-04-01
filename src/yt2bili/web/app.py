"""NiceGUI application factory for yt2bili."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import structlog
from nicegui import app as nicegui_app
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.config import AppConfig
from yt2bili.core.i18n import _, get_lang, set_lang
from yt2bili.core.paths import cache_dir
from yt2bili.services.avatar import AvatarService
from yt2bili.services.scheduler import SchedulerService
from yt2bili.services.trigger import TriggerService
from yt2bili.web.pages.channels import register_channels_page
from yt2bili.web.pages.settings import register_settings_page
from yt2bili.web.pages.tasks import register_tasks_page

log: structlog.stdlib.BoundLogger = structlog.get_logger()

# ── Navigation items ────────────────────────────────────────────────────────

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/", "nav.tasks", "assignment"),
    ("/channels", "nav.channels", "subscriptions"),
    ("/settings", "nav.settings", "settings"),
]


def _common_layout(active_path: str) -> None:
    """Render the shared top header with horizontal tab navigation."""
    with ui.header().classes("items-center justify-between px-4"):
        # Left: brand + nav tabs
        with ui.row().classes("items-center gap-4"):
            ui.label(_("app.brand")).classes("text-xl font-bold text-white")
            for path, label_key, icon in _NAV_ITEMS:
                is_active = active_path == path
                btn = ui.button(
                    _(label_key),
                    icon=icon,
                    on_click=lambda _, p=path: ui.navigate.to(p),
                )
                if is_active:
                    btn.props("flat text-color=white").classes("text-white font-bold bg-white/20 rounded")
                else:
                    btn.props("flat text-color=white/70").classes("text-white/70")

        # Right: language selector
        lang_options = {"en": "English", "zh-CN": "简体中文"}

        def _on_lang_change(e: Any) -> None:
            set_lang(e.value)
            ui.navigate.to(ui.context.client.page.path)

        ui.select(
            lang_options,
            value=get_lang(),
            on_change=_on_lang_change,
        ).classes("text-white").props("dense borderless dark")


class _AppState:
    """Mutable container shared between startup hook and page handlers."""

    session_factory: async_sessionmaker[AsyncSession] | None = None
    engine: Any = None
    download_stats: dict[int, dict] | None = None
    scheduler: SchedulerService | None = None
    trigger_service: TriggerService | None = None


_state = _AppState()


def create_app(
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    pipeline: Any | None = None,
    task_queue: Any | None = None,
    scheduler: Any | None = None,
    *,
    config_path: Path | None = None,
) -> None:
    """Configure NiceGUI pages and start the web server."""

    # Set the language from config
    set_lang(config.webui.language)

    if session_factory is not None:
        _state.session_factory = session_factory

    # ── avatar service ───────────────────────────────────────────────────
    avatar_service = AvatarService(config)
    avatar_dir = cache_dir() / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    nicegui_app.add_static_files("/avatars", str(avatar_dir))

    # ── startup / shutdown hooks ─────────────────────────────────────────

    async def _on_startup() -> None:
        if _state.session_factory is None:
            from yt2bili.db.engine import create_engine, create_session_factory

            _state.engine = await create_engine(config.database_url)
            _state.session_factory = create_session_factory(_state.engine)
            log.info("db.initialised", url=config.database_url)

        _state.download_stats = {}

        from yt2bili.services.downloader import VideoDownloader as _VideoDownloader
        from yt2bili.services.pipeline import Pipeline
        from yt2bili.services.subtitle import SubtitleService as _SubtitleService
        from yt2bili.services.task_queue import TaskQueue

        downloader = _VideoDownloader(config)
        subtitle_svc = _SubtitleService(config)

        try:
            from yt2bili.services.uploader import UploadService as _UploadService
            from yt2bili.core.schemas import UploadProgress
            import collections.abc

            class _NoOpBackend:
                async def authenticate(self, credentials: dict) -> bool:
                    return False

                async def upload(self, *args: Any, **kwargs: Any) -> str:
                    raise NotImplementedError("No uploader backend configured")

                def progress(self) -> collections.abc.AsyncIterator[UploadProgress]:
                    raise NotImplementedError("No uploader backend configured")

            upload_svc = _UploadService(_NoOpBackend(), config)  # type: ignore[arg-type]
        except Exception:
            upload_svc = None  # type: ignore[assignment]

        pipeline = Pipeline(
            downloader,  # type: ignore[arg-type]
            subtitle_svc,  # type: ignore[arg-type]
            upload_svc,  # type: ignore[arg-type]
            _state.session_factory,
            config,
            download_stats=_state.download_stats,
        )
        task_queue = TaskQueue(pipeline, _state.session_factory, config)
        await task_queue.start_workers(config.schedule.max_concurrent_downloads)

        trigger_svc = TriggerService(_state.session_factory, config, task_queue)

        class _MonitorAdapter:
            async def check_all_channels(self) -> list:
                result = await trigger_svc.check_all_channels()
                new_count = result.get("new_videos", 0)
                return [None] * new_count

        scheduler = SchedulerService(_MonitorAdapter(), config)  # type: ignore[arg-type]
        scheduler.start()

        _state.scheduler = scheduler
        _state.trigger_service = trigger_svc
        _state._task_queue = task_queue  # type: ignore[attr-defined]
        log.info("services.initialised")

    async def _on_shutdown() -> None:
        if _state.scheduler is not None:
            _state.scheduler.stop()
        task_queue = getattr(_state, "_task_queue", None)
        if task_queue is not None:
            await task_queue.stop()
        if _state.engine is not None:
            await _state.engine.dispose()
            log.info("db.disposed")

    nicegui_app.on_startup(_on_startup)
    nicegui_app.on_shutdown(_on_shutdown)

    # ── callback wiring ─────────────────────────────────────────────────

    check_all_callback: Callable[[], Any] | None = None
    if scheduler is not None and hasattr(scheduler, "check_all"):
        check_all_callback = scheduler.check_all
    elif task_queue is not None and hasattr(task_queue, "enqueue_check_all"):
        check_all_callback = task_queue.enqueue_check_all

    def _get_check_all_callback() -> Callable[[], Any] | None:
        if check_all_callback is not None:
            return check_all_callback
        if _state.trigger_service is not None:
            return _state.trigger_service.check_all_channels
        return None

    retry_callback: Callable[[int], Any] | None = None
    if task_queue is not None and hasattr(task_queue, "retry_task"):
        retry_callback = task_queue.retry_task

    cancel_callback: Callable[[int], Any] | None = None
    if task_queue is not None and hasattr(task_queue, "cancel_task"):
        cancel_callback = task_queue.cancel_task

    def _get_retry_callback() -> Callable[[int], Any] | None:
        if retry_callback is not None:
            return retry_callback
        if _state.trigger_service is not None:
            return _state.trigger_service.retry_task
        return None

    def _get_cancel_callback() -> Callable[[int], Any] | None:
        if cancel_callback is not None:
            return cancel_callback
        if _state.trigger_service is not None:
            return _state.trigger_service.cancel_task
        return None

    # ── page registration ───────────────────────────────────────────────

    def _factory() -> async_sessionmaker[AsyncSession]:
        assert _state.session_factory is not None, "DB not initialised yet"
        return _state.session_factory

    @ui.page("/")
    def tasks_page() -> None:
        _common_layout("/")
        register_tasks_page(
            _factory(),
            check_all_callback=_get_check_all_callback(),
            retry_callback=_get_retry_callback(),
            cancel_callback=_get_cancel_callback(),
            scheduler=_state.scheduler,
            download_stats=_state.download_stats,
            config=config,
        )

    @ui.page("/channels")
    def channels_page() -> None:
        _common_layout("/channels")
        register_channels_page(_factory(), config=config, avatar_service=avatar_service)

    @ui.page("/settings")
    def settings_page() -> None:
        _common_layout("/settings")
        register_settings_page(
            config,
            config_path=config_path,
            session_factory=_factory(),
        )

    log.info("webui.configured", host=config.webui.host, port=config.webui.port)

    ui.run(
        host=config.webui.host,
        port=config.webui.port,
        title=_("app.title"),
        storage_secret=config.webui.secret,
        show=False,
        reload=False,
    )
