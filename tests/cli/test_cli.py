"""Tests for the yt2bili CLI commands using Typer's CliRunner."""

from __future__ import annotations

from typing import Any, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from yt2bili.cli.main import app
from yt2bili.core.enums import TaskStatus

runner = CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_channel(
    *,
    id: int = 1,
    youtube_channel_id: str = "UC_test123",
    name: str = "Test Channel",
    enabled: bool = True,
    last_checked_at: Any = None,
    videos: list[Any] | None = None,
    config_overrides: str | None = None,
) -> MagicMock:
    ch = MagicMock()
    ch.id = id
    ch.youtube_channel_id = youtube_channel_id
    ch.name = name
    ch.enabled = enabled
    ch.last_checked_at = last_checked_at
    ch.videos = videos or []
    ch.config_overrides = config_overrides
    return ch


def _make_task(
    *,
    id: int = 1,
    video_id: int = 1,
    status: TaskStatus = TaskStatus.PENDING,
    progress_pct: float = 0.0,
    attempt: int = 0,
    error_message: str | None = None,
) -> MagicMock:
    t = MagicMock()
    t.id = id
    t.video_id = video_id
    t.status = status
    t.progress_pct = progress_pct
    t.attempt = attempt
    t.error_message = error_message
    return t


def _build_patches(
    *,
    channels: Sequence[Any] | None = None,
    tasks: Sequence[Any] | None = None,
    existing_channel: Any | None = None,
) -> tuple[Any, ...]:
    """Create patches for engine and Repository so CLI commands work without a real DB."""

    # Fake engine
    async def _fake_create_engine(url: str) -> AsyncMock:
        eng = AsyncMock()
        eng.dispose = AsyncMock()
        return eng

    # Fake session context manager
    fake_session = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self) -> AsyncMock:
            return fake_session

        async def __aexit__(self, *a: Any) -> None:
            pass

    def _fake_session_factory(engine: Any) -> Any:
        return lambda: _SessionCtx()

    # Fake repository
    mock_repo = MagicMock()
    mock_repo.list_channels = AsyncMock(return_value=list(channels or []))
    mock_repo.get_channel_by_youtube_id = AsyncMock(return_value=existing_channel)
    created_ch = _make_channel(youtube_channel_id="UC_new", name="New Channel")
    mock_repo.create_channel = AsyncMock(return_value=created_ch)
    mock_repo.list_tasks = AsyncMock(return_value=list(tasks or []))
    mock_repo.create_task = AsyncMock(return_value=_make_task(id=99, video_id=42))
    mock_repo.commit = AsyncMock()

    return (
        patch("yt2bili.db.engine.create_engine", side_effect=_fake_create_engine),
        patch("yt2bili.db.engine.create_session_factory", side_effect=_fake_session_factory),
        patch("yt2bili.cli.main.Repository", return_value=mock_repo),
    )


class _MultiPatch:
    """Combine multiple context managers."""

    def __init__(self, *cms: Any) -> None:
        self._cms = cms

    def __enter__(self) -> None:
        for cm in self._cms:
            cm.__enter__()

    def __exit__(self, *args: Any) -> None:
        for cm in reversed(self._cms):
            cm.__exit__(*args)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestListChannels:
    def test_no_channels(self) -> None:
        patches = _build_patches(channels=[])
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["list-channels"])
        assert result.exit_code == 0
        assert "No channels" in result.output

    def test_with_channels(self) -> None:
        channels = [
            _make_channel(id=1, youtube_channel_id="UC_abc", name="Alpha"),
            _make_channel(id=2, youtube_channel_id="UC_def", name="Beta", enabled=False),
        ]
        patches = _build_patches(channels=channels)
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["list-channels"])
        assert result.exit_code == 0
        assert "Alpha" in result.output
        assert "Beta" in result.output
        assert "UC_abc" in result.output


class TestAddChannel:
    def test_add_new(self) -> None:
        patches = _build_patches()
        with _MultiPatch(*patches), patch(
            "yt2bili.services.channel_resolver.resolve_channel",
            new_callable=AsyncMock,
            return_value=("UC_new", "New Channel"),
        ):
            result = runner.invoke(app, ["add-channel", "UC_new", "New Channel"])
        assert result.exit_code == 0
        assert "Added channel" in result.output

    def test_add_existing(self) -> None:
        existing = _make_channel(youtube_channel_id="UC_dup")
        patches = _build_patches(existing_channel=existing)
        with _MultiPatch(*patches), patch(
            "yt2bili.services.channel_resolver.resolve_channel",
            new_callable=AsyncMock,
            return_value=("UC_dup", "Dup"),
        ):
            result = runner.invoke(app, ["add-channel", "UC_dup", "Dup"])
        assert result.exit_code == 1

    def test_add_by_url_auto_name(self) -> None:
        patches = _build_patches()
        with _MultiPatch(*patches), patch(
            "yt2bili.services.channel_resolver.resolve_channel",
            new_callable=AsyncMock,
            return_value=("UC_resolved", "Auto Name"),
        ):
            result = runner.invoke(app, ["add-channel", "https://youtube.com/@handle"])
        assert result.exit_code == 0
        assert "Auto Name" in result.output

    def test_add_unresolvable(self) -> None:
        patches = _build_patches()
        with _MultiPatch(*patches), patch(
            "yt2bili.services.channel_resolver.resolve_channel",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = runner.invoke(app, ["add-channel", "garbage"])
        assert result.exit_code == 1
        assert "Could not resolve" in result.output


class TestStatus:
    def test_no_tasks(self) -> None:
        patches = _build_patches(tasks=[])
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No tasks" in result.output

    def test_with_tasks(self) -> None:
        tasks = [
            _make_task(id=1, status=TaskStatus.PENDING, progress_pct=0.0),
            _make_task(id=2, status=TaskStatus.COMPLETED, progress_pct=100.0),
        ]
        patches = _build_patches(tasks=tasks)
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Task Queue" in result.output


class TestCheckNow:
    def test_check_now(self) -> None:
        channels = [_make_channel(id=1, name="Active")]
        patches = _build_patches(channels=channels)
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["check-now"])
        assert result.exit_code == 0
        assert "1 enabled" in result.output


class TestUpload:
    def test_upload_creates_task(self) -> None:
        patches = _build_patches()
        with _MultiPatch(*patches):
            result = runner.invoke(app, ["upload", "42"])
        assert result.exit_code == 0
        assert "task" in result.output.lower()
