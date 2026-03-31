"""Tests for yt2bili.services.monitor – ChannelMonitor."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from yt2bili.core.config import AppConfig, ProxyConfig
from yt2bili.core.exceptions import MonitorError
from yt2bili.core.schemas import VideoMeta
from yt2bili.db.repository import Repository
from yt2bili.services.monitor import ChannelMonitor

# ── Sample RSS XML ──────────────────────────────────────────────────────────

_SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Test Channel</title>
  <entry>
    <yt:videoId>vid_new_001</yt:videoId>
    <title>Brand New Video</title>
    <published>2025-06-01T12:00:00+00:00</published>
    <media:group>
      <media:description>A great video description</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/vid_new_001/hqdefault.jpg" width="480" height="360"/>
    </media:group>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_new_001"/>
  </entry>
  <entry>
    <yt:videoId>vid_existing</yt:videoId>
    <title>Already Tracked Video</title>
    <published>2025-05-01T10:00:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_existing"/>
  </entry>
  <entry>
    <yt:videoId>vid_new_002</yt:videoId>
    <title>Another New Video</title>
    <published>2025-06-02T08:00:00+00:00</published>
    <media:group>
      <media:thumbnail url="https://i.ytimg.com/vi/vid_new_002/hqdefault.jpg" width="480" height="360"/>
    </media:group>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid_new_002"/>
  </entry>
</feed>
"""


def _make_channel(
    *,
    channel_id: int = 1,
    youtube_channel_id: str = "UC_test_channel",
    name: str = "Test Channel",
    enabled: bool = True,
) -> MagicMock:
    """Build a mock Channel object."""
    ch = MagicMock()
    ch.id = channel_id
    ch.youtube_channel_id = youtube_channel_id
    ch.name = name
    ch.enabled = enabled
    ch.config_overrides = None
    ch.last_checked_at = None
    ch.videos = []
    return ch


def _make_video(youtube_id: str = "vid_existing") -> MagicMock:
    """Build a mock Video object."""
    v = MagicMock()
    v.id = 99
    v.youtube_id = youtube_id
    return v


def _mock_repo() -> MagicMock:
    """Return a mock Repository with sensible defaults."""
    repo = MagicMock(spec=Repository)
    repo.get_video_by_youtube_id = AsyncMock(return_value=None)
    repo.list_channels = AsyncMock(return_value=[])
    repo.update_channel_checked = AsyncMock()
    repo.commit = AsyncMock()
    return repo


def _patch_httpx(response_text: str) -> Any:
    """Return a context-manager that patches httpx.AsyncClient."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.text = response_text
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    client_instance = AsyncMock()
    client_instance.get = AsyncMock(return_value=mock_response)

    ctx = patch("yt2bili.services.monitor.httpx.AsyncClient")
    return ctx, client_instance


# ── check_channel ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_channel_returns_new_videos() -> None:
    """New videos from the RSS feed should be returned as VideoMeta objects."""
    repo = _mock_repo()

    async def _fake_get_video(yt_id: str) -> MagicMock | None:
        if yt_id == "vid_existing":
            return _make_video()
        return None

    repo.get_video_by_youtube_id = AsyncMock(side_effect=_fake_get_video)
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)
    channel = _make_channel()

    ctx, client_instance = _patch_httpx(_SAMPLE_RSS)
    with ctx as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await monitor.check_channel(channel)

    assert len(result) == 2
    ids = {v.youtube_id for v in result}
    assert ids == {"vid_new_001", "vid_new_002"}
    for v in result:
        assert isinstance(v, VideoMeta)
        assert v.title  # non-empty title


@pytest.mark.asyncio
async def test_check_channel_skips_existing_videos() -> None:
    """Videos already in the DB must not appear in the result."""
    repo = _mock_repo()
    repo.get_video_by_youtube_id = AsyncMock(return_value=_make_video())
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)
    channel = _make_channel()

    ctx, client_instance = _patch_httpx(_SAMPLE_RSS)
    with ctx as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await monitor.check_channel(channel)

    # All 3 entries exist → no new videos
    assert result == []


@pytest.mark.asyncio
async def test_check_channel_raises_on_http_error() -> None:
    """MonitorError should be raised when the HTTP request fails."""
    repo = _mock_repo()
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)
    channel = _make_channel()

    with patch("yt2bili.services.monitor.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(MonitorError):
            await monitor.check_channel(channel)


@pytest.mark.asyncio
async def test_check_channel_extracts_metadata() -> None:
    """Verify that title and published date are extracted."""
    repo = _mock_repo()
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)
    channel = _make_channel()

    ctx, client_instance = _patch_httpx(_SAMPLE_RSS)
    with ctx as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await monitor.check_channel(channel)

    vid1 = next(v for v in result if v.youtube_id == "vid_new_001")
    assert vid1.title == "Brand New Video"
    assert vid1.youtube_upload_date is not None


# ── check_all_channels ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_all_channels_iterates_enabled() -> None:
    """check_all_channels should iterate all enabled channels."""
    ch1 = _make_channel(channel_id=1, youtube_channel_id="UC_ch1", name="Ch1")
    ch2 = _make_channel(channel_id=2, youtube_channel_id="UC_ch2", name="Ch2")
    repo = _mock_repo()
    repo.list_channels = AsyncMock(return_value=[ch1, ch2])
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)

    async def _fake_check(channel: MagicMock) -> list[VideoMeta]:
        return [
            VideoMeta(youtube_id=f"vid_{channel.id}", title=f"Video from {channel.name}")
        ]

    with patch.object(monitor, "check_channel", side_effect=_fake_check):
        result = await monitor.check_all_channels()

    assert len(result) == 2
    assert repo.update_channel_checked.call_count == 2
    repo.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_all_channels_continues_on_error() -> None:
    """If one channel fails, the others should still be checked."""
    ch1 = _make_channel(channel_id=1, youtube_channel_id="UC_fail")
    ch2 = _make_channel(channel_id=2, youtube_channel_id="UC_ok")
    repo = _mock_repo()
    repo.list_channels = AsyncMock(return_value=[ch1, ch2])
    config = AppConfig()
    monitor = ChannelMonitor(repo=repo, config=config)

    call_count = 0

    async def _fake_check(channel: MagicMock) -> list[VideoMeta]:
        nonlocal call_count
        call_count += 1
        if channel.youtube_channel_id == "UC_fail":
            raise MonitorError("boom")
        return [VideoMeta(youtube_id="vid_ok", title="OK")]

    with patch.object(monitor, "check_channel", side_effect=_fake_check):
        result = await monitor.check_all_channels()

    assert call_count == 2
    assert len(result) == 1
    assert result[0].youtube_id == "vid_ok"
    assert repo.update_channel_checked.call_count == 2


# ── Proxy propagation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_channel_passes_proxy_to_httpx() -> None:
    """httpx.AsyncClient should receive proxies from config."""
    repo = _mock_repo()
    config = AppConfig(proxy=ProxyConfig(http_proxy="http://proxy:3128"))
    monitor = ChannelMonitor(repo=repo, config=config)
    channel = _make_channel()

    ctx, client_instance = _patch_httpx(_SAMPLE_RSS)
    with ctx as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        await monitor.check_channel(channel)

    MockClient.assert_called_once_with(
        proxy="http://proxy:3128"
    )
