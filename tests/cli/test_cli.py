"""Tests for the yt2bili CLI — only the ``run`` command remains."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from yt2bili.cli.main import app

runner = CliRunner()


class TestRun:
    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Start the full application" in result.output

    def test_run_bad_config(self) -> None:
        result = runner.invoke(app, ["--config", "/nonexistent/path.yaml"])
        assert result.exit_code == 1

    def test_removed_commands_are_gone(self) -> None:
        """Ensure old commands like add-channel, list-channels, etc. no longer exist."""
        for cmd in ["add-channel", "list-channels", "check-now", "upload", "status"]:
            result = runner.invoke(app, [cmd])
            # Typer shows an error for unknown commands
            assert result.exit_code != 0
