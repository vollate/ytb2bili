"""Typer CLI application for yt2bili."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.table import Table

from yt2bili.core.config import AppConfig, load_config
from yt2bili.core.enums import TaskStatus
from yt2bili.core.i18n import _
from yt2bili.core.schemas import ChannelCreate
from yt2bili.db.repository import Repository

log: structlog.stdlib.BoundLogger = structlog.get_logger()
console = Console()

app = typer.Typer(
    name="yt2bili",
    help="YouTube channel subscription auto-repost to Bilibili.",
    add_completion=False,
)


def _load(config_path: Path | None) -> AppConfig:
    """Load and return AppConfig, exiting on failure."""
    try:
        return load_config(config_path)
    except Exception as exc:
        console.print(f"[red]{_('cli.error_loading_config')}[/red] {exc}")
        raise typer.Exit(code=1) from exc


async def _make_session_factory(config: AppConfig) -> tuple[object, object]:
    """Create engine + session factory from config."""
    from yt2bili.db.engine import create_engine, create_session_factory

    engine = await create_engine(config.database_url)
    factory = create_session_factory(engine)
    return engine, factory


# ── Commands ─────────────────────────────────────────────────────────────────


@app.command()
def run(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Start the full application (scheduler + web UI)."""
    cfg = _load(config_path)

    from yt2bili.web.app import create_app

    create_app(cfg, config_path=config_path)


@app.command()
def add_channel(
    channel: str = typer.Argument(
        ..., help="YouTube channel URL (e.g. https://youtube.com/@handle) or channel ID (UCxxx)"
    ),
    name: Optional[str] = typer.Argument(None, help="Display name (auto-fetched if omitted)"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Add a new YouTube channel to monitor.

    Accepts a YouTube channel URL (/@handle, /channel/UCxxx, /c/name, /user/name)
    or a bare channel ID.  The display name is auto-fetched from YouTube if not
    provided.
    """
    cfg = _load(config_path)

    async def _add() -> None:
        from yt2bili.services.channel_resolver import resolve_channel

        proxies = cfg.proxy.to_httpx_proxy()

        with console.status(f"[bold blue]{_('cli.resolving_channel')}"):
            result = await resolve_channel(channel, proxy=proxies)

        if result is None:
            console.print(f"[red]{_('cli.resolve_failed')}[/red] {channel}")
            console.print(_("cli.resolve_hint"))
            raise typer.Exit(code=1)

        channel_id, auto_name = result
        display_name = name if name else auto_name

        console.print(f"  Channel ID: [cyan]{channel_id}[/cyan]")
        console.print(f"  Name:       [cyan]{display_name}[/cyan]")

        engine, factory = await _make_session_factory(cfg)
        try:
            async with factory() as session:  # type: ignore[operator]
                repo = Repository(session)
                existing = await repo.get_channel_by_youtube_id(channel_id)
                if existing is not None:
                    console.print(f"[yellow]{_('cli.channel_exists', channel_id=channel_id, name=existing.name)}[/yellow]")
                    raise typer.Exit(code=1)
                ch = await repo.create_channel(
                    ChannelCreate(youtube_channel_id=channel_id, name=display_name)
                )
                await repo.commit()
                console.print(f"[green]{_('cli.channel_added', name=ch.name, channel_id=ch.youtube_channel_id)}[/green]")

            # Fetch and cache the channel avatar
            from yt2bili.services.avatar import AvatarService

            avatar_svc = AvatarService(cfg)
            with console.status("[bold blue]Fetching avatar..."):
                avatar_path = await avatar_svc.fetch_avatar(channel_id)
            if avatar_path is not None:
                console.print(f"  Avatar cached: [dim]{avatar_path}[/dim]")
            else:
                console.print("  [yellow]Avatar not found or could not be downloaded.[/yellow]")
        finally:
            await engine.dispose()  # type: ignore[union-attr]

    asyncio.run(_add())


@app.command()
def list_channels(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """List all monitored YouTube channels."""
    cfg = _load(config_path)

    async def _list() -> None:
        engine, factory = await _make_session_factory(cfg)
        try:
            async with factory() as session:  # type: ignore[operator]
                repo = Repository(session)
                channels = await repo.list_channels()
        finally:
            await engine.dispose()  # type: ignore[union-attr]

        if not channels:
            console.print(f"[yellow]{_('cli.no_channels')}[/yellow]")
            return

        table = Table(title=_("cli.table_channels"))
        table.add_column("ID", style="dim")
        table.add_column("YouTube ID", style="cyan")
        table.add_column("Name")
        table.add_column("Enabled", justify="center")
        table.add_column("Last Checked")

        for ch in channels:
            table.add_row(
                str(ch.id),
                ch.youtube_channel_id,
                ch.name,
                "✓" if ch.enabled else "✗",
                ch.last_checked_at.strftime("%Y-%m-%d %H:%M") if ch.last_checked_at else _("channels.card.never_checked"),
            )
        console.print(table)

    asyncio.run(_list())


@app.command()
def check_now(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Trigger an immediate check of all enabled channels."""
    cfg = _load(config_path)

    async def _check() -> None:
        engine, factory = await _make_session_factory(cfg)
        try:
            async with factory() as session:  # type: ignore[operator]
                repo = Repository(session)
                channels = await repo.list_channels(enabled_only=True)
            console.print(f"[green]{_('cli.enabled_channels', count=str(len(channels)))}[/green]")
            for ch in channels:
                console.print(f"  • {ch.name} ({ch.youtube_channel_id})")
            console.print(f"[yellow]{_('cli.scheduler_note')}[/yellow]")
        finally:
            await engine.dispose()  # type: ignore[union-attr]

    asyncio.run(_check())


@app.command()
def upload(
    video_id: int = typer.Argument(..., help="Database video ID to upload"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Manually trigger upload for a specific video."""
    cfg = _load(config_path)

    async def _upload() -> None:
        engine, factory = await _make_session_factory(cfg)
        try:
            async with factory() as session:  # type: ignore[operator]
                repo = Repository(session)
                task = await repo.create_task(video_id=video_id, priority=10)
                await repo.commit()
                console.print(f"[green]{_('cli.task_created', task_id=str(task.id), video_id=str(video_id))}[/green]")
        finally:
            await engine.dispose()  # type: ignore[union-attr]

    asyncio.run(_upload())


@app.command()
def status(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Show current task queue status."""
    cfg = _load(config_path)

    async def _status() -> None:
        engine, factory = await _make_session_factory(cfg)
        try:
            async with factory() as session:  # type: ignore[operator]
                repo = Repository(session)
                tasks = await repo.list_tasks(limit=50)
        finally:
            await engine.dispose()  # type: ignore[union-attr]

        if not tasks:
            console.print(f"[yellow]{_('cli.no_tasks')}[/yellow]")
            return

        table = Table(title=_("cli.table_tasks"))
        table.add_column("ID", style="dim")
        table.add_column("Video ID")
        table.add_column("Status")
        table.add_column("Progress", justify="right")
        table.add_column("Attempt", justify="center")
        table.add_column("Error")

        status_colors: dict[TaskStatus, str] = {
            TaskStatus.PENDING: "white",
            TaskStatus.DOWNLOADING: "blue",
            TaskStatus.SUBTITLING: "magenta",
            TaskStatus.UPLOADING: "yellow",
            TaskStatus.COMPLETED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.RETRYING: "yellow",
            TaskStatus.CANCELLED: "dim",
        }

        for t in tasks:
            color = status_colors.get(t.status, "white")
            table.add_row(
                str(t.id),
                str(t.video_id),
                f"[{color}]{t.status.value}[/{color}]",
                f"{t.progress_pct:.0f}%",
                str(t.attempt),
                (t.error_message or "")[:60],
            )
        console.print(table)

    asyncio.run(_status())


if __name__ == "__main__":
    app()
