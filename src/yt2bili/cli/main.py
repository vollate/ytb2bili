"""Typer CLI application for yt2bili."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console

from yt2bili.core.config import load_config
from yt2bili.core.i18n import _

log: structlog.stdlib.BoundLogger = structlog.get_logger()
console = Console()

app = typer.Typer(
    name="yt2bili",
    help="YouTube channel subscription auto-repost to Bilibili.",
    add_completion=False,
)


@app.command()
def run(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
) -> None:
    """Start the full application (scheduler + web UI)."""
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        console.print(f"[red]{_('cli.error_loading_config')}[/red] {exc}")
        raise typer.Exit(code=1) from exc

    from yt2bili.web.app import create_app

    create_app(cfg, config_path=config_path)


if __name__ == "__main__":
    app()
