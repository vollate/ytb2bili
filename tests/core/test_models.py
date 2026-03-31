"""Tests for yt2bili.core.models ORM layer."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.models import Base, BilibiliCredential, Channel, Task, Video


# ── Channel basic CRUD ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_creation(db_session: AsyncSession) -> None:
    """A Channel can be persisted and read back."""
    channel = Channel(youtube_channel_id="UC_test_123", name="Test Channel")
    db_session.add(channel)
    await db_session.flush()

    assert channel.id is not None
    assert channel.youtube_channel_id == "UC_test_123"
    assert channel.name == "Test Channel"
    assert channel.enabled is True  # default
    assert channel.config_overrides is None


@pytest.mark.asyncio
async def test_channel_defaults(db_session: AsyncSession) -> None:
    """Channel has correct default values."""
    channel = Channel(youtube_channel_id="UC_defaults", name="Defaults Channel")
    db_session.add(channel)
    await db_session.flush()

    assert channel.enabled is True
    assert channel.last_checked_at is None
    assert channel.created_at is not None
    assert channel.updated_at is not None


@pytest.mark.asyncio
async def test_channel_unique_youtube_id(db_session: AsyncSession) -> None:
    """Duplicate youtube_channel_id raises IntegrityError."""
    c1 = Channel(youtube_channel_id="UC_dup", name="First")
    c2 = Channel(youtube_channel_id="UC_dup", name="Second")
    db_session.add(c1)
    await db_session.flush()

    db_session.add(c2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── Channel config_overrides helpers ────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_get_config_overrides_none(db_session: AsyncSession) -> None:
    """get_config_overrides returns empty dict when field is None."""
    channel = Channel(youtube_channel_id="UC_cfg1", name="CfgNone")
    db_session.add(channel)
    await db_session.flush()

    assert channel.get_config_overrides() == {}


@pytest.mark.asyncio
async def test_channel_set_and_get_config_overrides(db_session: AsyncSession) -> None:
    """Round-trip JSON serialization of config_overrides."""
    channel = Channel(youtube_channel_id="UC_cfg2", name="CfgTest")
    db_session.add(channel)
    await db_session.flush()

    overrides: dict[str, Any] = {"quality": "1080", "tags": ["a", "b"]}
    channel.set_config_overrides(overrides)
    await db_session.flush()

    got = channel.get_config_overrides()
    assert got == overrides


@pytest.mark.asyncio
async def test_channel_set_config_overrides_empty_dict(db_session: AsyncSession) -> None:
    """set_config_overrides({}) sets the field to None."""
    channel = Channel(youtube_channel_id="UC_cfg3", name="CfgEmpty")
    channel.set_config_overrides({"key": "val"})
    db_session.add(channel)
    await db_session.flush()

    channel.set_config_overrides({})
    await db_session.flush()
    assert channel.config_overrides is None
    assert channel.get_config_overrides() == {}


# ── Video ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_creation(db_session: AsyncSession) -> None:
    """Video requires a parent Channel via FK."""
    channel = Channel(youtube_channel_id="UC_vid", name="VidCh")
    db_session.add(channel)
    await db_session.flush()

    video = Video(
        youtube_id="dQw4w9WgXcQ",
        channel_id=channel.id,
        title="Test Video",
    )
    db_session.add(video)
    await db_session.flush()

    assert video.id is not None
    assert video.channel_id == channel.id
    assert video.description is None
    assert video.duration is None


@pytest.mark.asyncio
async def test_video_unique_youtube_id(db_session: AsyncSession) -> None:
    """Duplicate youtube_id raises IntegrityError."""
    ch = Channel(youtube_channel_id="UC_vdup", name="VDup")
    db_session.add(ch)
    await db_session.flush()

    v1 = Video(youtube_id="SAME_ID", channel_id=ch.id, title="V1")
    v2 = Video(youtube_id="SAME_ID", channel_id=ch.id, title="V2")
    db_session.add(v1)
    await db_session.flush()

    db_session.add(v2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── Relationships ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_video_relationship(db_session: AsyncSession) -> None:
    """Channel.videos backref works."""
    ch = Channel(youtube_channel_id="UC_rel", name="RelCh")
    db_session.add(ch)
    await db_session.flush()

    v1 = Video(youtube_id="vid_a", channel_id=ch.id, title="A")
    v2 = Video(youtube_id="vid_b", channel_id=ch.id, title="B")
    db_session.add_all([v1, v2])
    await db_session.flush()

    # Refresh to load relationship
    await db_session.refresh(ch)
    assert len(ch.videos) == 2
    ids = {v.youtube_id for v in ch.videos}
    assert ids == {"vid_a", "vid_b"}


@pytest.mark.asyncio
async def test_video_channel_backref(db_session: AsyncSession) -> None:
    """Video.channel relationship resolves to the parent Channel."""
    ch = Channel(youtube_channel_id="UC_br", name="BRCh")
    db_session.add(ch)
    await db_session.flush()

    vid = Video(youtube_id="vid_br", channel_id=ch.id, title="BR")
    db_session.add(vid)
    await db_session.flush()

    await db_session.refresh(vid)
    assert vid.channel.id == ch.id
    assert vid.channel.name == "BRCh"


@pytest.mark.asyncio
async def test_video_task_relationship(db_session: AsyncSession) -> None:
    """Video→Task one-to-many relationship works."""
    ch = Channel(youtube_channel_id="UC_vt", name="VTCh")
    db_session.add(ch)
    await db_session.flush()

    vid = Video(youtube_id="vid_vt", channel_id=ch.id, title="VT")
    db_session.add(vid)
    await db_session.flush()

    t1 = Task(video_id=vid.id, status=TaskStatus.PENDING)
    t2 = Task(video_id=vid.id, status=TaskStatus.DOWNLOADING)
    db_session.add_all([t1, t2])
    await db_session.flush()

    await db_session.refresh(vid)
    assert len(vid.tasks) == 2
    statuses = {t.status for t in vid.tasks}
    assert TaskStatus.PENDING in statuses
    assert TaskStatus.DOWNLOADING in statuses


@pytest.mark.asyncio
async def test_task_video_backref(db_session: AsyncSession) -> None:
    """Task.video resolves to the parent Video."""
    ch = Channel(youtube_channel_id="UC_tb", name="TBCh")
    db_session.add(ch)
    await db_session.flush()

    vid = Video(youtube_id="vid_tb", channel_id=ch.id, title="TB")
    db_session.add(vid)
    await db_session.flush()

    task = Task(video_id=vid.id)
    db_session.add(task)
    await db_session.flush()

    await db_session.refresh(task)
    assert task.video.id == vid.id
    assert task.video.title == "TB"


# ── Task ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_defaults(db_session: AsyncSession) -> None:
    """Task has correct default field values."""
    ch = Channel(youtube_channel_id="UC_td", name="TDCh")
    db_session.add(ch)
    await db_session.flush()
    vid = Video(youtube_id="vid_td", channel_id=ch.id, title="TD")
    db_session.add(vid)
    await db_session.flush()

    task = Task(video_id=vid.id)
    db_session.add(task)
    await db_session.flush()

    assert task.status == TaskStatus.PENDING
    assert task.priority == 0
    assert task.progress_pct == 0.0
    assert task.attempt == 0
    assert task.video_path is None
    assert task.subtitle_path is None
    assert task.subtitle_source is None
    assert task.bilibili_bvid is None
    assert task.error_message is None


@pytest.mark.asyncio
async def test_task_with_all_fields(db_session: AsyncSession) -> None:
    """Task can be created with all optional fields set."""
    ch = Channel(youtube_channel_id="UC_tf", name="TFCh")
    db_session.add(ch)
    await db_session.flush()
    vid = Video(youtube_id="vid_tf", channel_id=ch.id, title="TF")
    db_session.add(vid)
    await db_session.flush()

    task = Task(
        video_id=vid.id,
        status=TaskStatus.COMPLETED,
        priority=5,
        progress_pct=100.0,
        attempt=2,
        video_path="/tmp/video.mp4",
        subtitle_path="/tmp/sub.srt",
        subtitle_source=SubtitleSource.YOUTUBE_MANUAL,
        bilibili_bvid="BV1234567890",
        error_message=None,
    )
    db_session.add(task)
    await db_session.flush()

    assert task.status == TaskStatus.COMPLETED
    assert task.priority == 5
    assert task.progress_pct == 100.0
    assert task.attempt == 2
    assert task.video_path == "/tmp/video.mp4"
    assert task.subtitle_source == SubtitleSource.YOUTUBE_MANUAL
    assert task.bilibili_bvid == "BV1234567890"


# ── BilibiliCredential ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bilibili_credential_creation(db_session: AsyncSession) -> None:
    """BilibiliCredential can be persisted."""
    cred = BilibiliCredential(
        label="main",
        sessdata="sess_abc",
        bili_jct="jct_abc",
        buvid3="buvid_abc",
    )
    db_session.add(cred)
    await db_session.flush()

    assert cred.id is not None
    assert cred.is_active is True
    assert cred.expires_at is None
    assert cred.created_at is not None
