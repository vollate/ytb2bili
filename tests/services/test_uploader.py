"""Tests for the upload service."""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import TaskStatus
from yt2bili.core.exceptions import UploadError
from yt2bili.core.models import Channel, Task, Video
from yt2bili.core.schemas import UploadProgress
from yt2bili.services.uploader import UploadServiceWithCredential


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(overrides: dict[str, Any] | None = None) -> Channel:
    ch = Channel(
        id=1,
        youtube_channel_id="UC_test",
        name="Test Channel",
        enabled=True,
    )
    if overrides:
        ch.set_config_overrides(overrides)
    return ch


def _make_video() -> Video:
    return Video(
        id=1,
        youtube_id="dQw4w9WgXcQ",
        channel_id=1,
        title="Original Title",
        description="Original desc",
        duration=212,
    )


def _make_task() -> Task:
    t = Task(
        id=1,
        video_id=1,
        status=TaskStatus.UPLOADING,
        progress_pct=60.0,
    )
    return t


class FakeBackend:
    """Minimal mock implementing UploaderBackend protocol."""

    def __init__(self, bvid: str = "BV1xx411c7mD") -> None:
        self.authenticate = AsyncMock(return_value=True)
        self.upload = AsyncMock(return_value=bvid)
        self._progress_events: list[UploadProgress] = []

    async def progress(self) -> AsyncIterator[UploadProgress]:
        for ev in self._progress_events:
            yield ev


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_video_basic() -> None:
    """Default config: title/desc templates are applied."""
    backend = FakeBackend()
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    video = _make_video()
    channel = _make_channel()
    task = _make_task()
    video_path = Path("/tmp/video.mp4")

    bvid = await svc.upload_video(task, video, channel, video_path, None)

    assert bvid == "BV1xx411c7mD"
    backend.authenticate.assert_awaited_once_with(credential)
    backend.upload.assert_awaited_once()

    call_kwargs = backend.upload.call_args.kwargs
    assert call_kwargs["title"] == "Original Title"
    assert "dQw4w9WgXcQ" in call_kwargs["description"]
    assert call_kwargs["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert call_kwargs["partition_id"] == 17
    assert call_kwargs["tags"] == ["搬运", "YouTube"]


@pytest.mark.asyncio
async def test_upload_video_channel_overrides() -> None:
    """Per-channel overrides take precedence over global config."""
    backend = FakeBackend()
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    overrides = {
        "title_template": "[Repost] {original_title}",
        "tags": ["自制"],
        "bilibili_tid": 42,
    }
    channel = _make_channel(overrides)
    video = _make_video()
    task = _make_task()

    bvid = await svc.upload_video(task, video, channel, Path("/v.mp4"), None)

    assert bvid == "BV1xx411c7mD"
    kw = backend.upload.call_args.kwargs
    assert kw["title"] == "[Repost] Original Title"
    assert kw["tags"] == ["自制"]
    assert kw["partition_id"] == 42


@pytest.mark.asyncio
async def test_upload_video_auth_failure() -> None:
    """UploadError is raised when authenticate returns False."""
    backend = FakeBackend()
    backend.authenticate = AsyncMock(return_value=False)
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    with pytest.raises(UploadError, match="rejected"):
        await svc.upload_video(
            _make_task(), _make_video(), _make_channel(), Path("/v.mp4"), None
        )


@pytest.mark.asyncio
async def test_upload_video_backend_exception() -> None:
    """UploadError wraps arbitrary backend exceptions."""
    backend = FakeBackend()
    backend.upload = AsyncMock(side_effect=RuntimeError("boom"))
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    with pytest.raises(UploadError, match="boom"):
        await svc.upload_video(
            _make_task(), _make_video(), _make_channel(), Path("/v.mp4"), None
        )


@pytest.mark.asyncio
async def test_upload_progress_mapping() -> None:
    """Progress callback receives values in the 60-95 % range."""
    backend = FakeBackend()
    backend._progress_events = [
        UploadProgress(uploaded_bytes=0, total_bytes=100),
        UploadProgress(uploaded_bytes=50, total_bytes=100),
        UploadProgress(uploaded_bytes=100, total_bytes=100),
    ]
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    progress_values: list[float] = []

    async def _cb(pct: float) -> None:
        progress_values.append(pct)

    await svc.upload_video(
        _make_task(), _make_video(), _make_channel(), Path("/v.mp4"), None,
        progress_callback=_cb,
    )

    assert len(progress_values) == 3
    assert progress_values[0] == pytest.approx(60.0)
    assert progress_values[1] == pytest.approx(77.5)
    assert progress_values[2] == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_upload_desc_template_placeholders() -> None:
    """Description template correctly substitutes youtube_url and description."""
    backend = FakeBackend()
    config = AppConfig()
    credential = {"sessdata": "s", "bili_jct": "j", "buvid3": "b"}
    svc = UploadServiceWithCredential(backend, config, credential)

    video = _make_video()
    video.description = "Hello world"

    await svc.upload_video(
        _make_task(), video, _make_channel(), Path("/v.mp4"), None
    )

    desc = backend.upload.call_args.kwargs["description"]
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in desc
    assert "Hello world" in desc
