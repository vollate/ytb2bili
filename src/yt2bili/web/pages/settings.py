"""Settings page — tabs layout with auth integration."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from nicegui import ui
from nicegui.events import UploadEventArguments
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.config import AppConfig
from yt2bili.core.i18n import _, translations
from yt2bili.core.paths import cache_dir, default_config_path
from yt2bili.core.schemas import BilibiliCredentialCreate
from yt2bili.db.repository import Repository

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def register_settings_page(
    config: AppConfig,
    *,
    config_path: Path | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Build the settings editor UI with tabs layout inside the current NiceGUI page context."""

    inputs: dict[str, dict[str, ui.input | ui.number | ui.switch | ui.textarea]] = {}
    _containers: dict[str, Any] = {}

    # ── Field builder helpers ────────────────────────────────────────────

    def _field(section_key: str, field_name: str, obj: object) -> None:
        """Render a single config field with label and hint."""
        current_value = getattr(obj, field_name)
        annotation = obj.__class__.model_fields[field_name].annotation
        i18n_key = f"settings.field.{field_name}"
        hint_key = f"{i18n_key}.hint"
        label = _(i18n_key) if i18n_key in translations.get("en", {}) else field_name
        hint = _(hint_key) if hint_key in translations.get("en", {}) else ""

        if annotation is bool or isinstance(current_value, bool):
            inp = ui.switch(label, value=current_value)
            if hint:
                inp.tooltip(hint)
        elif annotation is int or isinstance(current_value, int):
            inp = ui.number(label, value=float(current_value)).classes("w-full")
            if hint:
                ui.label(hint).classes("text-xs text-grey-5 ml-1 -mt-1")
        elif annotation is float or isinstance(current_value, float):
            inp = ui.number(label, value=current_value, step=0.1).classes("w-full")
            if hint:
                ui.label(hint).classes("text-xs text-grey-5 ml-1 -mt-1")
        elif isinstance(current_value, list):
            inp = ui.input(label, value=", ".join(str(v) for v in current_value)).classes("w-full")
            if hint:
                ui.label(hint).classes("text-xs text-grey-5 ml-1 -mt-1")
        elif isinstance(current_value, Path):
            inp = ui.input(label, value=str(current_value)).classes("w-full")
            if hint:
                ui.label(hint).classes("text-xs text-grey-5 ml-1 -mt-1")
        else:
            inp = ui.input(label, value=str(current_value) if current_value is not None else "").classes("w-full")
            if hint:
                ui.label(hint).classes("text-xs text-grey-5 ml-1 -mt-1")

        inputs.setdefault(section_key, {})[field_name] = inp

    def _section_fields(section_key: str, obj: object) -> None:
        """Render all fields for a config section."""
        with ui.column().classes("w-full gap-3"):
            for field_name in obj.__class__.model_fields:
                _field(section_key, field_name, obj)

    # ── Proxy section ────────────────────────────────────────────────────

    def _proxy_section(proxy: object) -> None:
        inputs["proxy"] = {}
        with ui.column().classes("w-full gap-3"):
            enabled_sw = ui.switch(
                _("settings.field.proxy_enabled"),
                value=getattr(proxy, "enabled", False),
            )
            inputs["proxy"]["enabled"] = enabled_sw

            with ui.row().classes("w-full items-end gap-3"):
                type_sel = ui.select(
                    {"http": "HTTP", "https": "HTTPS", "socks5": "SOCKS5"},
                    value=getattr(proxy, "proxy_type", "http"),
                    label=_("settings.field.proxy_type"),
                ).classes("w-36").props("dense outlined")
                inputs["proxy"]["proxy_type"] = type_sel

                host_inp = ui.input(
                    _("settings.field.proxy_host"),
                    value=getattr(proxy, "host", ""),
                ).classes("flex-1").props("dense outlined")
                inputs["proxy"]["host"] = host_inp

                port_inp = ui.number(
                    _("settings.field.proxy_port"),
                    value=float(getattr(proxy, "port", 0)),
                    min=0, max=65535,
                ).classes("w-28").props("dense outlined")
                inputs["proxy"]["port"] = port_inp

            auth_sw = ui.switch(
                _("settings.field.proxy_auth_enabled"),
                value=getattr(proxy, "auth_enabled", False),
            )
            inputs["proxy"]["auth_enabled"] = auth_sw

            auth_row = ui.row().classes("w-full items-end gap-3")
            with auth_row:
                user_inp = ui.input(
                    _("settings.field.proxy_username"),
                    value=getattr(proxy, "username", ""),
                ).classes("flex-1").props("dense outlined")
                inputs["proxy"]["username"] = user_inp

                pass_inp = ui.input(
                    _("settings.field.proxy_password"),
                    value=getattr(proxy, "password", ""),
                    password=True, password_toggle_button=True,
                ).classes("flex-1").props("dense outlined")
                inputs["proxy"]["password"] = pass_inp

            auth_row.bind_visibility_from(auth_sw, "value")

            no_proxy_inp = ui.input(
                _("settings.field.no_proxy"),
                value=getattr(proxy, "no_proxy", ""),
                placeholder="localhost,127.0.0.1,.example.com",
            ).classes("w-full").props("dense outlined")
            inputs["proxy"]["no_proxy"] = no_proxy_inp

    # ── Auth tab content ─────────────────────────────────────────────────

    def _auth_section() -> None:
        """Render the Auth tab: Bilibili credentials + YouTube cookies."""

        # ── Bilibili credentials ─────────────────────────────────────
        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(_("auth.title")).classes("text-lg font-bold")
                ui.button(_("auth.add"), icon="add", on_click=_open_add_cred_dialog).props("color=primary dense")

            _containers["cred_list"] = ui.element("div").classes("w-full")

            ui.separator().classes("my-4")

            # ── YouTube cookies ──────────────────────────────────────
            ui.label(_("auth.youtube.title")).classes("text-lg font-bold")
            _containers["yt_cookies"] = ui.element("div").classes("w-full")

        _refresh_yt_section()
        if session_factory is not None:
            ui.timer(interval=0.1, callback=_refresh_credentials, once=True)

    async def _refresh_credentials() -> None:
        if session_factory is None:
            return
        async with session_factory() as session:
            repo = Repository(session)
            credentials = await repo.list_credentials()

        _containers["cred_list"].clear()
        with _containers["cred_list"]:
            if not credentials:
                ui.label(_("auth.no_credentials")).classes("text-grey-6")
            else:
                with ui.column().classes("w-full gap-2"):
                    for cred in credentials:
                        _credential_card(cred)

    def _credential_card(cred: Any) -> None:
        with ui.card().classes("w-full").props("flat bordered"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(cred.label).classes("text-base font-bold")
                        if cred.is_active:
                            ui.badge(_("auth.active"), color="positive").props("dense")
                        else:
                            ui.badge(_("auth.inactive"), color="grey").props("dense")
                    masked = f"{'*' * 8}...{cred.sessdata[-4:]}"
                    ui.label(_("auth.sessdata_display", masked=masked)).classes("text-xs font-mono text-grey-6")
                    if cred.expires_at:
                        ui.label(_("auth.expires_display", date=f"{cred.expires_at:%Y-%m-%d}")).classes("text-xs text-grey-6")

                with ui.row().classes("gap-1"):
                    if not cred.is_active:
                        ui.button(
                            _("auth.set_active"),
                            on_click=lambda _, cid=cred.id: _set_active(cid),
                        ).props("flat dense size=sm color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda _, cid=cred.id: _delete_cred(cid),
                        color="negative",
                    ).props("flat dense round size=sm")

    async def _set_active(credential_id: int) -> None:
        if session_factory is None:
            return
        async with session_factory() as session:
            repo = Repository(session)
            creds = await repo.list_credentials()
            for c in creds:
                c.is_active = c.id == credential_id
            await repo.commit()
        ui.notify(_("auth.activated"), type="positive")
        await _refresh_credentials()

    async def _delete_cred(credential_id: int) -> None:
        if session_factory is None:
            return
        async with session_factory() as session:
            repo = Repository(session)
            await repo.delete_credential(credential_id)
            await repo.commit()
        ui.notify(_("auth.deleted"), type="warning")
        await _refresh_credentials()

    async def _add_credential(label: str, sessdata: str, bili_jct: str, buvid3: str, expires: str) -> None:
        if session_factory is None:
            return
        if not all(v.strip() for v in [label, sessdata, bili_jct, buvid3]):
            ui.notify(_("auth.fields_required"), type="negative")
            return
        expires_at: datetime.datetime | None = None
        if expires.strip():
            try:
                expires_at = datetime.datetime.fromisoformat(expires.strip())
            except ValueError:
                ui.notify(_("auth.invalid_date"), type="negative")
                return

        async with session_factory() as session:
            repo = Repository(session)
            await repo.create_credential(
                BilibiliCredentialCreate(
                    label=label.strip(),
                    sessdata=sessdata.strip(),
                    bili_jct=bili_jct.strip(),
                    buvid3=buvid3.strip(),
                    expires_at=expires_at,
                )
            )
            await repo.commit()
        ui.notify(_("auth.added"), type="positive")
        await _refresh_credentials()

    def _open_add_cred_dialog() -> None:
        with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
            ui.label(_("auth.add_dialog_title")).classes("text-lg font-bold mb-2")
            label_input = ui.input(_("auth.label")).classes("w-full")
            sessdata_input = ui.input(_("auth.sessdata")).classes("w-full").props("type=password")
            bili_jct_input = ui.input(_("auth.bili_jct")).classes("w-full").props("type=password")
            buvid3_input = ui.input(_("auth.buvid3")).classes("w-full").props("type=password")
            expires_input = ui.input(_("auth.expires_at")).classes("w-full")

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
                ui.button(
                    _("common.add"),
                    on_click=lambda: _add_credential(
                        label_input.value,
                        sessdata_input.value,
                        bili_jct_input.value,
                        buvid3_input.value,
                        expires_input.value,
                    ),
                ).props("color=primary")
        dlg.open()

    # ── YouTube cookies helpers ──────────────────────────────────────────

    def _get_cookies_path() -> Path:
        return cache_dir() / "youtube_cookies.txt"

    def _get_cookies_content() -> str:
        cookies_file = config.download.youtube_cookies_file if config else None
        if cookies_file:
            p = Path(cookies_file)
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8")
                except Exception:
                    return ""
        return ""

    async def _save_cookies_path(cookies_path: str | None) -> None:
        save_path = config_path or default_config_path()
        existing: dict[str, Any] = {}
        if save_path.exists():
            existing = yaml.safe_load(save_path.read_text()) or {}
        existing.setdefault("download", {})["youtube_cookies_file"] = cookies_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(yaml.dump(existing, default_flow_style=False, allow_unicode=True))
        if config:
            config.download.youtube_cookies_file = cookies_path

    async def _save_cookies_text(text: str) -> None:
        dest = _get_cookies_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        await _save_cookies_path(str(dest))
        ui.notify(_("auth.youtube.file_saved"), type="positive")
        _refresh_yt_section()

    async def _on_upload(e: UploadEventArguments) -> None:
        dest = _get_cookies_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(e.content.read())
        await _save_cookies_path(str(dest))
        ui.notify(_("auth.youtube.file_saved"), type="positive")
        _refresh_yt_section()

    async def _on_clear() -> None:
        p = _get_cookies_path()
        if p.exists():
            p.unlink()
        await _save_cookies_path(None)
        ui.notify(_("auth.youtube.file_cleared"), type="warning")
        _refresh_yt_section()

    def _refresh_yt_section() -> None:
        _containers["yt_cookies"].clear()
        with _containers["yt_cookies"]:
            cookies_file = config.download.youtube_cookies_file if config else None
            content = _get_cookies_content()

            if cookies_file:
                p = Path(cookies_file)
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle", color="positive" if p.exists() else "negative", size="xs")
                    if p.exists():
                        ui.label(_("auth.youtube.file_exists", path=cookies_file)).classes("text-xs text-positive")
                    else:
                        ui.label(_("auth.youtube.file_missing", path=cookies_file)).classes("text-xs text-negative")
            else:
                ui.label(_("auth.youtube.no_cookies")).classes("text-grey-6 text-sm")

            ui.label(_("auth.youtube.editor_label")).classes("text-sm font-medium mt-3")
            cookie_editor = ui.textarea(
                value=content,
                placeholder=_("auth.youtube.editor_placeholder"),
            ).classes("w-full font-mono text-xs").props("rows=10 outlined")

            ui.label(_("auth.youtube.hint")).classes("text-xs text-grey-6 mt-1")

            with ui.row().classes("gap-2 mt-2"):
                ui.button(
                    _("auth.youtube.save_text"), icon="save",
                    on_click=lambda: _save_cookies_text(cookie_editor.value or ""),
                ).props("color=primary dense")

                ui.upload(
                    on_upload=_on_upload, auto_upload=True,
                    label=_("auth.youtube.upload"),
                ).props("accept=.txt").classes("max-w-xs")

                if cookies_file:
                    ui.button(
                        _("auth.youtube.clear"), icon="delete",
                        on_click=_on_clear, color="negative",
                    ).props("flat dense")

    # ── Collect values and save ──────────────────────────────────────────

    def _collect_values() -> dict[str, object]:
        result: dict[str, object] = {}
        for section_key, field_map in inputs.items():
            section_data: dict[str, object] = {}
            section_obj = getattr(config, section_key, None)
            if section_obj is None:
                continue
            for field_name, widget in field_map.items():
                original = getattr(section_obj, field_name)
                raw = widget.value
                if isinstance(original, bool):
                    section_data[field_name] = bool(raw)
                elif isinstance(original, int):
                    section_data[field_name] = int(raw)
                elif isinstance(original, float):
                    section_data[field_name] = float(raw)
                elif isinstance(original, list):
                    section_data[field_name] = [s.strip() for s in str(raw).split(",") if s.strip()]
                elif isinstance(original, Path):
                    section_data[field_name] = str(raw)
                else:
                    if isinstance(original, str):
                        section_data[field_name] = str(raw) if raw else ""
                    else:
                        section_data[field_name] = raw if raw else None
            result[section_key] = section_data
        return result

    async def _save() -> None:
        data = _collect_values()
        data["database_url"] = config.database_url

        save_path = config_path or default_config_path()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            yaml.dump(dict(data), default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        log.info("settings.saved", path=str(save_path))
        ui.notify(_("settings.saved", path=str(save_path)), type="positive")

    # ── Page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4 max-w-4xl mx-auto"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("settings.title")).classes("text-2xl font-bold")
            ui.button(_("settings.save"), icon="save", on_click=_save).props("color=primary")

        # Horizontal tabs
        with ui.tabs().classes("w-full") as tabs:
            tab_scheduler = ui.tab("scheduler", label=_("settings.tab.scheduler"), icon="schedule")
            tab_download = ui.tab("download", label=_("settings.tab.download"), icon="download")
            tab_upload = ui.tab("upload", label=_("settings.tab.upload"), icon="upload")
            tab_subtitle = ui.tab("subtitle", label=_("settings.tab.subtitle"), icon="subtitles")
            tab_network = ui.tab("network", label=_("settings.tab.network"), icon="language")
            tab_auth = ui.tab("auth", label=_("settings.tab.auth"), icon="key")

        with ui.tab_panels(tabs, value="scheduler").classes("w-full"):
            with ui.tab_panel("scheduler"):
                _section_fields("schedule", config.schedule)

            with ui.tab_panel("download"):
                _section_fields("download", config.download)

            with ui.tab_panel("upload"):
                _section_fields("upload", config.upload)

            with ui.tab_panel("subtitle"):
                _section_fields("subtitle", config.subtitle)

            with ui.tab_panel("network"):
                _proxy_section(config.proxy)

            with ui.tab_panel("auth"):
                _auth_section()
