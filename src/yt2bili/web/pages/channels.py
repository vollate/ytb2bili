"""Channels management page — list, add, toggle, delete, edit overrides."""

from __future__ import annotations

from typing import Any

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import VideoQuality
from yt2bili.core.i18n import _
from yt2bili.core.schemas import ChannelCreate, ChannelUpdate
from yt2bili.db.repository import Repository
from yt2bili.services.avatar import AvatarService
from yt2bili.web.components.channel_card import render_channel_card
from yt2bili.web.state import Ref

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def register_channels_page(
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig | None = None,
    avatar_service: AvatarService | None = None,
) -> None:
    """Build the channels management UI inside the current NiceGUI page context."""

    _containers: dict[str, Any] = {}
    search_query = Ref[str]("")

    # ── helpers ───────────────────────────────────────────────────────

    async def _refresh() -> None:
        async with session_factory() as session:
            repo = Repository(session)
            channels = list(await repo.list_channels())

        # Stats
        total = len(channels)
        enabled = sum(1 for c in channels if c.enabled)
        disabled = total - enabled
        _containers["stats_label"].set_text(
            _("channels.stats", total=str(total), enabled=str(enabled), disabled=str(disabled))
        )

        # Filter by search
        query = search_query.value.lower().strip()
        if query:
            channels = [
                c for c in channels
                if query in c.name.lower() or query in c.youtube_channel_id.lower()
            ]

        # Sort by name
        channels.sort(key=lambda c: c.name.lower())

        _containers["channel_list"].clear()
        with _containers["channel_list"]:
            if not channels:
                ui.label(_("channels.no_channels")).classes("text-grey-6")
            else:
                with ui.column().classes("w-full gap-3"):
                    for ch in channels:
                        avatar_url: str | None = None
                        if avatar_service is not None:
                            cached = avatar_service.get_cached_path(ch.youtube_channel_id)
                            if cached is not None:
                                avatar_url = f"/avatars/{ch.youtube_channel_id}.jpg"
                        render_channel_card(
                            ch,
                            avatar_path=avatar_url,
                            on_toggle=_toggle_channel,
                            on_delete=_delete_channel,
                            on_edit=_open_edit_dialog,
                        )

    async def _toggle_channel(channel_id: int, enabled: bool) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.update_channel(channel_id, ChannelUpdate(enabled=enabled))
            await repo.commit()
        await _refresh()

    async def _delete_channel(channel_id: int) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.delete_channel(channel_id)
            await repo.commit()
        ui.notify(_("channels.deleted"), type="warning")
        await _refresh()

    async def _add_channel_resolved(
        channel_input: str,
        name_override: str,
        quality: str | None,
        tags: str,
        subtitle_langs: str,
        rss_feeds: list[str],
        status_label_el: Any,
        dlg: Any,
    ) -> None:
        from yt2bili.services.channel_resolver import resolve_channel

        channel_input = channel_input.strip()
        if not channel_input:
            ui.notify(_("channels.add_dialog.url_required"), type="negative")
            return

        status_label_el.set_text(_("channels.add_dialog.resolving"))
        status_label_el.set_visibility(True)

        proxies = config.proxy.to_httpx_proxy() if config else None
        result = await resolve_channel(channel_input, proxy=proxies)

        if result is None:
            status_label_el.set_text("")
            status_label_el.set_visibility(False)
            ui.notify(_("channels.add_dialog.resolve_failed"), type="negative")
            return

        channel_id, auto_name = result
        display_name = name_override.strip() if name_override.strip() else auto_name

        overrides: dict[str, Any] = {}
        if quality and quality != "default":
            overrides["quality"] = quality
        if tags.strip():
            overrides["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if subtitle_langs.strip():
            overrides["subtitle_langs"] = [s.strip() for s in subtitle_langs.split(",") if s.strip()]
        if rss_feeds:
            overrides["rss_feeds"] = rss_feeds

        async with session_factory() as session:
            repo = Repository(session)
            existing = await repo.get_channel_by_youtube_id(channel_id)
            if existing is not None:
                status_label_el.set_text("")
                status_label_el.set_visibility(False)
                ui.notify(_("channels.add_dialog.already_exists", name=existing.name), type="negative")
                return
            await repo.create_channel(
                ChannelCreate(
                    youtube_channel_id=channel_id,
                    name=display_name,
                    config_overrides=overrides if overrides else None,
                )
            )
            await repo.commit()
        ui.notify(_("channels.add_dialog.added", name=display_name), type="positive")
        dlg.close()

        if avatar_service is not None:
            await avatar_service.fetch_avatar(channel_id)

        await _refresh()

    def _open_add_dialog() -> None:
        with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
            ui.label(_("channels.add_dialog.title")).classes("text-lg font-bold mb-2")

            channel_input = ui.input(
                _("channels.add_dialog.url_or_id"),
                placeholder=_("channels.add_dialog.url_placeholder"),
            ).classes("w-full")

            name_input = ui.input(
                _("channels.add_dialog.name_optional"),
                placeholder=_("channels.add_dialog.name_placeholder"),
            ).classes("w-full")

            ui.separator()
            ui.label(_("channels.add_dialog.overrides")).classes("text-xs text-grey-6")
            quality_options = [_("common.default")] + [q.value for q in VideoQuality]
            quality_select = ui.select(
                quality_options, value=_("common.default"), label=_("channels.add_dialog.quality")
            ).classes("w-full")
            tags_input = ui.input(
                _("channels.add_dialog.tags"), placeholder=_("channels.add_dialog.tags_placeholder")
            ).classes("w-full")
            sub_langs_input = ui.input(
                _("channels.add_dialog.subtitle_langs"),
                placeholder=_("channels.add_dialog.subtitle_langs_placeholder"),
            ).classes("w-full")

            ui.separator()
            ui.label(_("channels.add_dialog.rss_feeds_label")).classes("text-xs text-grey-6 mb-1")
            ui.label(_("channels.add_dialog.rss_feeds_hint")).classes("text-xs text-grey-5 mb-2")
            _rss_selection: dict[str, bool] = {"all": True, "videos": True, "shorts": True, "live": True}
            with ui.row().classes("gap-4"):
                for feed_type, label_key in [
                    ("all", "channels.rss.all"),
                    ("videos", "channels.rss.videos"),
                    ("shorts", "channels.rss.shorts"),
                    ("live", "channels.rss.live"),
                ]:
                    cb = ui.checkbox(_(label_key), value=True)
                    cb.on("update:model-value", lambda e, ft=feed_type: _rss_selection.update({ft: bool(e.value)}))

            status_label_el = ui.label("").classes("text-sm text-blue-6")
            status_label_el.set_visibility(False)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
                ui.button(
                    _("common.add"),
                    on_click=lambda: _add_channel_resolved(
                        channel_input.value,
                        name_input.value,
                        quality_select.value,
                        tags_input.value,
                        sub_langs_input.value,
                        [ft for ft, v in _rss_selection.items() if v],
                        status_label_el,
                        dlg,
                    ),
                ).props("color=primary")
        dlg.open()

    def _open_edit_dialog(channel_id: int) -> None:
        async def _load_and_show() -> None:
            async with session_factory() as session:
                repo = Repository(session)
                channel = await repo.get_channel(channel_id)
            if channel is None:
                ui.notify(_("channels.edit_dialog.not_found"), type="negative")
                return

            overrides: dict[str, Any] = channel.get_config_overrides()

            with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
                ui.label(_("channels.edit_dialog.title", name=channel.name)).classes("text-lg font-bold mb-2")
                ui.label(_("channels.edit_dialog.overrides_label")).classes("text-xs text-grey-6 mb-2")

                quality_options = [q.value for q in VideoQuality]
                current_quality = overrides.get("quality", "")
                quality_select = ui.select(
                    quality_options,
                    value=current_quality if current_quality in quality_options else None,
                    label=_("channels.edit_dialog.quality"),
                    clearable=True,
                ).classes("w-full")

                current_tags = overrides.get("tags", [])
                tags_input = ui.input(
                    _("channels.edit_dialog.tags"),
                    value=", ".join(current_tags) if isinstance(current_tags, list) else "",
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                current_sub = overrides.get("subtitle_langs", [])
                sub_langs_input = ui.input(
                    _("channels.edit_dialog.subtitle_langs"),
                    value=", ".join(current_sub) if isinstance(current_sub, list) else "",
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                current_tid = overrides.get("bilibili_tid")
                tid_input = ui.number(
                    _("channels.edit_dialog.tid"),
                    value=current_tid if current_tid is not None else None,
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                title_tpl_input = ui.input(
                    _("channels.edit_dialog.title_template"),
                    value=overrides.get("title_template", ""),
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                desc_tpl_input = ui.textarea(
                    _("channels.edit_dialog.desc_template"),
                    value=overrides.get("desc_template", ""),
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full").props("rows=3")

                # RSS feed types
                ui.separator()
                ui.label(_("channels.edit_dialog.rss_feeds")).classes("text-xs text-grey-6 mb-1")
                current_feeds: list[str] = overrides.get("rss_feeds") or ["all", "videos", "shorts", "live"]
                _edit_rss: dict[str, bool] = {ft: ft in current_feeds for ft in ["all", "videos", "shorts", "live"]}
                with ui.row().classes("gap-4"):
                    for feed_type, label_key in [
                        ("all", "channels.rss.all"),
                        ("videos", "channels.rss.videos"),
                        ("shorts", "channels.rss.shorts"),
                        ("live", "channels.rss.live"),
                    ]:
                        cb = ui.checkbox(_(label_key), value=feed_type in current_feeds)
                        cb.on("update:model-value", lambda e, ft=feed_type: _edit_rss.update({ft: bool(e.value)}))

                current_extra: list[str] = overrides.get("extra_playlists") or []
                extra_playlists_input = ui.textarea(
                    _("channels.edit_dialog.rss_extra_playlists"),
                    value="\n".join(current_extra),
                    placeholder=_("channels.edit_dialog.rss_extra_playlists_placeholder"),
                ).classes("w-full").props("rows=4")

                async def _save() -> None:
                    new_overrides: dict[str, Any] = {}
                    if quality_select.value:
                        new_overrides["quality"] = quality_select.value
                    tags_val: str = tags_input.value or ""
                    if tags_val.strip():
                        new_overrides["tags"] = [t.strip() for t in tags_val.split(",") if t.strip()]
                    sub_val: str = sub_langs_input.value or ""
                    if sub_val.strip():
                        new_overrides["subtitle_langs"] = [s.strip() for s in sub_val.split(",") if s.strip()]
                    if tid_input.value is not None:
                        new_overrides["bilibili_tid"] = int(tid_input.value)
                    title_val: str = title_tpl_input.value or ""
                    if title_val.strip():
                        new_overrides["title_template"] = title_val.strip()
                    desc_val: str = desc_tpl_input.value or ""
                    if desc_val.strip():
                        new_overrides["desc_template"] = desc_val.strip()
                    selected_feeds = [ft for ft, v in _edit_rss.items() if v]
                    if selected_feeds and set(selected_feeds) != {"all", "videos", "shorts", "live"}:
                        new_overrides["rss_feeds"] = selected_feeds
                    extra_raw: str = extra_playlists_input.value or ""
                    extra_ids = [line.strip() for line in extra_raw.splitlines() if line.strip()]
                    if extra_ids:
                        new_overrides["extra_playlists"] = extra_ids

                    async with session_factory() as sess:
                        r = Repository(sess)
                        await r.update_channel(channel_id, ChannelUpdate(config_overrides=new_overrides))
                        await r.commit()
                    ui.notify(_("channels.edit_dialog.saved"), type="positive")
                    dlg.close()
                    await _refresh()

                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
                    ui.button(_("common.save"), on_click=_save).props("color=primary")
            dlg.open()

        ui.timer(interval=0.01, callback=_load_and_show, once=True)

    # ── page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4 max-w-4xl mx-auto"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.label(_("channels.title")).classes("text-2xl font-bold")
                _containers["stats_label"] = ui.label("").classes("text-sm text-grey-6")
            with ui.row().classes("gap-2"):
                search_input = ui.input(
                    placeholder=_("channels.search_placeholder"),
                ).classes("w-56").props("dense clearable outlined")

                def _on_search(e: Any) -> None:
                    search_query.value = e.value or ""

                search_input.on("update:model-value", _on_search)
                search_input.on("update:model-value", lambda _: _refresh())

                ui.button(_("channels.add"), icon="add", on_click=_open_add_dialog).props("color=primary")

        _containers["channel_list"] = ui.element("div").classes("w-full")

    ui.timer(interval=0.1, callback=_refresh, once=True)
