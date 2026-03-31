"""Bilibili credential management page."""

from __future__ import annotations

import datetime
from typing import Any

import structlog
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yt2bili.core.i18n import _
from yt2bili.core.schemas import BilibiliCredentialCreate
from yt2bili.db.repository import Repository

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def register_auth_page(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Build the Bilibili credential management UI."""

    cred_container = ui.element("div").classes("w-full")

    # ── helpers ───────────────────────────────────────────────────────────

    async def _refresh() -> None:
        async with session_factory() as session:
            repo = Repository(session)
            credentials = await repo.list_credentials()

        cred_container.clear()
        with cred_container:
            if not credentials:
                ui.label(_("auth.no_credentials")).classes("text-grey-6")
            else:
                with ui.column().classes("w-full gap-2"):
                    for cred in credentials:
                        _credential_card(cred)

    def _credential_card(cred: Any) -> None:
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(cred.label).classes("text-lg font-bold")
                        if cred.is_active:
                            ui.badge(_("auth.active"), color="positive").classes("text-xs")
                        else:
                            ui.badge(_("auth.inactive"), color="grey").classes("text-xs")
                    masked = f"{'*' * 8}...{cred.sessdata[-4:]}"
                    ui.label(_("auth.sessdata_display", masked=masked)).classes("text-xs font-mono text-grey-6")
                    if cred.expires_at:
                        ui.label(_("auth.expires_display", date=f"{cred.expires_at:%Y-%m-%d}")).classes("text-xs text-grey-6")
                    ui.label(_("auth.added_display", date=f"{cred.created_at:%Y-%m-%d %H:%M}")).classes("text-xs text-grey-6")

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
                    ).props("flat dense round size=sm").tooltip(_("auth.delete"))

    async def _set_active(credential_id: int) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            creds = await repo.list_credentials()
            # Deactivate all, then activate the chosen one
            for c in creds:
                c.is_active = c.id == credential_id
            await repo.commit()
        log.info("credential.activated", credential_id=credential_id)
        ui.notify(_("auth.activated"), type="positive")
        await _refresh()

    async def _delete_cred(credential_id: int) -> None:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.delete_credential(credential_id)
            await repo.commit()
        log.info("credential.deleted", credential_id=credential_id)
        ui.notify(_("auth.deleted"), type="warning")
        await _refresh()

    async def _add_credential(label: str, sessdata: str, bili_jct: str, buvid3: str, expires: str) -> None:
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
        log.info("credential.added", label=label)
        ui.notify(_("auth.added"), type="positive")
        await _refresh()

    def _open_add_dialog() -> None:
        with ui.dialog() as dlg, ui.card().classes("w-[500px]"):
            ui.label(_("auth.add_dialog_title")).classes("text-lg font-bold mb-2")
            label_input = ui.input(_("auth.label")).classes("w-full")
            sessdata_input = ui.input(_("auth.sessdata")).classes("w-full").props('type=password')
            bili_jct_input = ui.input(_("auth.bili_jct")).classes("w-full").props('type=password')
            buvid3_input = ui.input(_("auth.buvid3")).classes("w-full").props('type=password')
            expires_input = ui.input(_("auth.expires_at")).classes("w-full")

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button(_("common.cancel"), on_click=dlg.close).props("flat")
                ui.button(
                    _("common.add"),
                    on_click=lambda: _add_credential(
                        label_input.value,  # type: ignore[arg-type]
                        sessdata_input.value,  # type: ignore[arg-type]
                        bili_jct_input.value,  # type: ignore[arg-type]
                        buvid3_input.value,  # type: ignore[arg-type]
                        expires_input.value,  # type: ignore[arg-type]
                    ),
                ).props("color=primary")
        dlg.open()

    # ── page layout ──────────────────────────────────────────────────────

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(_("auth.title")).classes("text-2xl font-bold")
            with ui.row().classes("gap-2"):
                ui.button(_("common.refresh"), icon="refresh", on_click=_refresh).props("flat")
                ui.button(_("auth.add"), icon="add", on_click=_open_add_dialog).props("color=primary")

        cred_container  # noqa: B018

    ui.timer(interval=0.1, callback=_refresh, once=True)
