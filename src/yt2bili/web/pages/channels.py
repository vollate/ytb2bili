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

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def register_channels_page(
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig | None = None,
    avatar_service: AvatarService | None = None,
) -> None:
    """Build the channels management UI inside the current NiceGUI page context."""

    channel_list_container = ui.element("div").classes("w-full")
    stats_label = ui.label("").classes("text-sm text-grey-6")

    # ── state ─────────────────────────────────────────────────────────
    _search_query: dict[str, str] = {"value": ""}
    _sort_key: dict[str, str] = {"value": "name"}

    # ── helpers ───────────────────────────────────────────────────────

    async def _refresh() -> None:
        async with session_factory() as session:
            repo = Repository(session)
            channels = list(await repo.list_channels())

        # Stats row
        total = len(channels)
        enabled = sum(1 for c in channels if c.enabled)
        disabled = total - enabled
        stats_label.set_text(
            _("channels.stats", total=str(total), enabled=str(enabled), disabled=str(disabled))
        )

        # Filter
        query = _search_query["value"].lower().strip()
        if query:
            channels = [
                c
                for c in channels
                if query in c.name.lower() or query in c.youtube_channel_id.lower()
            ]

        # Sort
        sort = _sort_key["value"]
        if sort == "name":
            channels.sort(key=lambda c: c.name.lower())
        elif sort == "last_checked":
            channels.sort(
                key=lambda c: c.last_checked_at or __import__("datetime").datetime.min,
                reverse=True,
            )
        elif sort == "video_count":
            channels.sort(
                key=lambda c: len(c.videos) if hasattr(c, "videos") and c.videos else 0,
                reverse=True,
            )

        channel_list_container.clear()
        with channel_list_container:
            if not channels:
                ui.label(_("channels.no_channels")).classes("text-grey-6")
            else:
                with ui.row().classes("w-full flex-wrap gap-4"):
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
        log.info("channel.toggled", channel_id=channel_id, enabled=enabled)
        await _refresh()

    async def _bulk_set_enabled(enabled: bool) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            channels = await repo.list_channels()
            for ch in channels:
                await repo.update_channel(ch.id, ChannelUpdate(enabled=enabled))
            await repo.commit()
        state = _("common.enabled") if enabled else _("common.disabled")
        ui.notify(_("channels.toggled", state=state), type="positive")
        await _refresh()

    async def _delete_channel(channel_id: int) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.delete_channel(channel_id)
            await repo.commit()
        log.info("channel.deleted", channel_id=channel_id)
        ui.notify(_("channels.deleted"), type="warning")
        await _refresh()

    async def _add_channel_resolved(
        channel_input: str,
        name_override: str,
        quality: str | None,
        tags: str,
        subtitle_langs: str,
        status_label_el: Any,
        dlg: Any,
    ) -> None:
        """Resolve channel URL/ID, auto-fetch name if empty, then create."""
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
            ui.notify(
                _("channels.add_dialog.resolve_failed"),
                type="negative",
            )
            return

        channel_id, auto_name = result
        display_name = name_override.strip() if name_override.strip() else auto_name

        # Build optional config overrides
        overrides: dict[str, Any] = {}
        if quality and quality != "default":
            overrides["quality"] = quality
        if tags.strip():
            overrides["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if subtitle_langs.strip():
            overrides["subtitle_langs"] = [
                s.strip() for s in subtitle_langs.split(",") if s.strip()
            ]

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
        log.info("channel.added", youtube_channel_id=channel_id, name=display_name)
        ui.notify(_("channels.add_dialog.added", name=display_name), type="positive")
        dlg.close()

        # Fetch avatar before refreshing so it's available for display
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
                _("channels.add_dialog.subtitle_langs"), placeholder=_("channels.add_dialog.subtitle_langs_placeholder")
            ).classes("w-full")

            status_label_el = ui.label("").classes("text-sm text-blue-6")
            status_label_el.set_visibility(False)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
                ui.button(
                    _("common.add"),
                    on_click=lambda: _add_channel_resolved(
                        channel_input.value,  # type: ignore[arg-type]
                        name_input.value,  # type: ignore[arg-type]
                        quality_select.value,  # type: ignore[arg-type]
                        tags_input.value,  # type: ignore[arg-type]
                        sub_langs_input.value,  # type: ignore[arg-type]
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

                # Quality dropdown
                quality_options = [q.value for q in VideoQuality]
                current_quality = overrides.get("quality", "")
                quality_select = ui.select(
                    quality_options,
                    value=current_quality if current_quality in quality_options else None,
                    label=_("channels.edit_dialog.quality"),
                    clearable=True,
                ).classes("w-full")
                quality_select.props(f'placeholder="{_("channels.edit_dialog.using_default")}"')

                # Tags
                current_tags = overrides.get("tags", [])
                tags_input = ui.input(
                    _("channels.edit_dialog.tags"),
                    value=", ".join(current_tags) if isinstance(current_tags, list) else "",
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                # Subtitle languages
                current_sub = overrides.get("subtitle_langs", [])
                sub_langs_input = ui.input(
                    _("channels.edit_dialog.subtitle_langs"),
                    value=", ".join(current_sub) if isinstance(current_sub, list) else "",
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                # Bilibili TID
                current_tid = overrides.get("bilibili_tid")
                tid_input = ui.number(
                    _("channels.edit_dialog.tid"),
                    value=current_tid if current_tid is not None else None,
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                # Title template
                title_tpl_input = ui.input(
                    _("channels.edit_dialog.title_template"),
                    value=overrides.get("title_template", ""),
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full")

                # Description template
                desc_tpl_input = ui.textarea(
                    _("channels.edit_dialog.desc_template"),
                    value=overrides.get("desc_template", ""),
                    placeholder=_("channels.edit_dialog.using_default"),
                ).classes("w-full").props("rows=3")

                async def _save() -> None:
                    new_overrides: dict[str, Any] = {}
                    if quality_select.value:
                        new_overrides["quality"] = quality_select.value
                    tags_val: str = tags_input.value or ""  # type: ignore[assignment]
                    if tags_val.strip():
                        new_overrides["tags"] = [
                            t.strip() for t in tags_val.split(",") if t.strip()
                        ]
                    sub_val: str = sub_langs_input.value or ""  # type: ignore[assignment]
                    if sub_val.strip():
                        new_overrides["subtitle_langs"] = [
                            s.strip() for s in sub_val.split(",") if s.strip()
                        ]
                    if tid_input.value is not None:
                        new_overrides["bilibili_tid"] = int(tid_input.value)
                    title_val: str = title_tpl_input.value or ""  # type: ignore[assignment]
                    if title_val.strip():
                        new_overrides["title_template"] = title_val.strip()
                    desc_val: str = desc_tpl_input.value or ""  # type: ignore[assignment]
                    if desc_val.strip():
                        new_overrides["desc_template"] = desc_val.strip()

                    async with session_factory() as sess:
                        r = Repository(sess)
                        await r.update_channel(
                            channel_id, ChannelUpdate(config_overrides=new_overrides)
                        )
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

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("channels.title")).classes("text-2xl font-bold")
            with ui.row().classes("gap-2"):
                ui.button(_("channels.refresh"), icon="refresh", on_click=_refresh).props("flat")
                ui.button(_("channels.add"), icon="add", on_click=_open_add_dialog).props(
                    "color=primary"
                )

        # Stats row
        stats_label  # noqa: B018

        # Search + Sort + Bulk actions
        with ui.row().classes("w-full items-center gap-4"):
            search_input = ui.input(
                _("channels.search_label"), placeholder=_("channels.search_placeholder")
            ).classes("flex-1").props('dense clearable outlined')

            def _on_search(e: Any) -> None:
                _search_query["value"] = e.value or ""

            search_input.on("update:model-value", _on_search)
            search_input.on(
                "update:model-value",
                lambda _: _refresh(),  # type: ignore[arg-type, return-value]
            )

            sort_select = ui.select(
                {
                    "name": _("channels.sort.name"),
                    "last_checked": _("channels.sort.last_checked"),
                    "video_count": _("channels.sort.video_count"),
                },
                value="name",
                label=_("channels.sort_by"),
            ).classes("w-40").props("dense outlined")

            def _on_sort(e: Any) -> None:
                _sort_key["value"] = e.value or "name"

            sort_select.on(
                "update:model-value",
                _on_sort,
            )
            sort_select.on(
                "update:model-value",
                lambda _: _refresh(),  # type: ignore[arg-type, return-value]
            )

            ui.button(_("channels.enable_all"), on_click=lambda: _bulk_set_enabled(True)).props(
                "flat dense"
            )
            ui.button(_("channels.disable_all"), on_click=lambda: _bulk_set_enabled(False)).props(
                "flat dense"
            )

        channel_list_container  # noqa: B018

    ui.timer(interval=0.1, callback=_refresh, once=True)
