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
from yt2bili.web.pages.auth import register_auth_page
from yt2bili.web.pages.channels import register_channels_page
from yt2bili.web.pages.dashboard import register_dashboard_page
from yt2bili.web.pages.settings import register_settings_page
from yt2bili.web.pages.tasks import register_tasks_page
from yt2bili.web.pages.videos import register_videos_page

log: structlog.stdlib.BoundLogger = structlog.get_logger()

# ── Navigation items ────────────────────────────────────────────────────────

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/", "nav.dashboard", "dashboard"),
    ("/channels", "nav.channels", "subscriptions"),
    ("/videos", "nav.videos", "video_library"),
    ("/tasks", "nav.tasks", "list_alt"),
    ("/settings", "nav.settings", "settings"),
    ("/auth", "nav.auth", "key"),
]


def _common_layout(title_key: str) -> None:
    """Render the shared header + left-drawer navigation."""
    with ui.header().classes("items-center justify-between px-4"):
        ui.label(_("app.brand")).classes("text-xl font-bold text-white")
        ui.label(_(title_key)).classes("text-sm text-white/70")

        # Language selector
        lang_options = {"en": "English", "zh-CN": "简体中文"}

        def _on_lang_change(e: Any) -> None:
            set_lang(e.value)
            ui.navigate.to(ui.context.client.page.path)

        ui.select(
            lang_options,
            value=get_lang(),
            on_change=_on_lang_change,
        ).classes("text-white").props("dense borderless dark")

    with ui.left_drawer(value=True).classes("bg-grey-2"):
        ui.label(_("nav.navigation")).classes("text-xs text-grey-6 px-4 pt-4 pb-2")
        for path, label_key, icon in _NAV_ITEMS:
            ui.button(_(label_key), icon=icon, on_click=lambda _, p=path: ui.navigate.to(p)).props(
                "flat align=left"
            ).classes("w-full")


class _AppState:
    """Mutable container shared between startup hook and page handlers."""

    session_factory: async_sessionmaker[AsyncSession] | None = None
    engine: Any = None


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
    """Configure NiceGUI pages and start the web server.

    The database engine is initialised inside NiceGUI's own event loop via the
    ``app.on_startup`` hook so there is no nested ``asyncio.run()`` conflict.

    Parameters
    ----------
    config:
        The validated application configuration.
    session_factory:
        Optional pre-built session factory.  When ``None`` (the normal CLI
        path) the factory is created lazily on startup.
    pipeline:
        Optional pipeline service (for triggering manual uploads).
    task_queue:
        Optional task-queue service (for enqueuing check-all).
    scheduler:
        Optional APScheduler instance (for triggering immediate checks).
    config_path:
        Path to the YAML config file (for the settings page save).
    """

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

    async def _on_shutdown() -> None:
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

    retry_callback: Callable[[int], Any] | None = None
    if task_queue is not None and hasattr(task_queue, "retry_task"):
        retry_callback = task_queue.retry_task

    cancel_callback: Callable[[int], Any] | None = None
    if task_queue is not None and hasattr(task_queue, "cancel_task"):
        cancel_callback = task_queue.cancel_task

    # ── page registration ───────────────────────────────────────────────

    def _factory() -> async_sessionmaker[AsyncSession]:
        assert _state.session_factory is not None, "DB not initialised yet"
        return _state.session_factory

    @ui.page("/")
    def dashboard_page() -> None:
        _common_layout("nav.dashboard")
        register_dashboard_page(_factory(), check_all_callback=check_all_callback, avatar_service=avatar_service)

    @ui.page("/channels")
    def channels_page() -> None:
        _common_layout("nav.channels")
        register_channels_page(_factory(), config=config, avatar_service=avatar_service)

    @ui.page("/videos")
    def videos_page() -> None:
        _common_layout("nav.videos")
        register_videos_page(_factory())

    @ui.page("/tasks")
    def tasks_page() -> None:
        _common_layout("nav.tasks")
        register_tasks_page(
            _factory(),
            retry_callback=retry_callback,
            cancel_callback=cancel_callback,
        )

    @ui.page("/settings")
    def settings_page() -> None:
        _common_layout("nav.settings")
        register_settings_page(config, config_path=config_path)

    @ui.page("/auth")
    def auth_page() -> None:
        _common_layout("nav.auth")
        register_auth_page(_factory())

    log.info("webui.configured", host=config.webui.host, port=config.webui.port)

    ui.run(
        host=config.webui.host,
        port=config.webui.port,
        title=_("app.title"),
        storage_secret=config.webui.secret,
        show=False,
        reload=False,
    )
