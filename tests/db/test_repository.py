"""Tests for yt2bili.db.repository CRUD operations."""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.models import BilibiliCredential, Channel, Task, Video
from yt2bili.core.schemas import (
    BilibiliCredentialCreate,
    ChannelCreate,
    ChannelUpdate,
    VideoMeta,
)
from yt2bili.db.repository import Repository


# ── Channel CRUD ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_channel(repo: Repository) -> None:
    data = ChannelCreate(youtube_channel_id="UC_repo1", name="Repo Channel")
    ch = await repo.create_channel(data)

    assert ch.id is not None
    assert ch.youtube_channel_id == "UC_repo1"
    assert ch.name == "Repo Channel"
    assert ch.enabled is True
    assert ch.config_overrides is None


@pytest.mark.asyncio
async def test_create_channel_with_overrides(repo: Repository) -> None:
    data = ChannelCreate(
        youtube_channel_id="UC_over",
        name="Override",
        config_overrides={"quality": "720"},
    )
    ch = await repo.create_channel(data)
    assert ch.config_overrides is not None
    assert "720" in ch.config_overrides


@pytest.mark.asyncio
async def test_get_channel(repo: Repository) -> None:
    data = ChannelCreate(youtube_channel_id="UC_get", name="Get")
    ch = await repo.create_channel(data)

    fetched = await repo.get_channel(ch.id)
    assert fetched is not None
    assert fetched.id == ch.id
    assert fetched.name == "Get"


@pytest.mark.asyncio
async def test_get_channel_not_found(repo: Repository) -> None:
    result = await repo.get_channel(9999)
    assert result is None


@pytest.mark.asyncio
async def test_get_channel_by_youtube_id(repo: Repository) -> None:
    data = ChannelCreate(youtube_channel_id="UC_byyt", name="ByYT")
    await repo.create_channel(data)

    found = await repo.get_channel_by_youtube_id("UC_byyt")
    assert found is not None
    assert found.name == "ByYT"

    missing = await repo.get_channel_by_youtube_id("UC_nonexistent")
    assert missing is None


@pytest.mark.asyncio
async def test_list_channels(repo: Repository) -> None:
    await repo.create_channel(ChannelCreate(youtube_channel_id="UC_la", name="A"))
    await repo.create_channel(ChannelCreate(youtube_channel_id="UC_lb", name="B"))

    channels = await repo.list_channels()
    assert len(channels) == 2


@pytest.mark.asyncio
async def test_list_channels_enabled_only(repo: Repository) -> None:
    await repo.create_channel(ChannelCreate(youtube_channel_id="UC_en", name="Enabled"))
    await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_dis", name="Disabled", enabled=False)
    )

    all_ch = await repo.list_channels()
    assert len(all_ch) == 2

    enabled = await repo.list_channels(enabled_only=True)
    assert len(enabled) == 1
    assert enabled[0].name == "Enabled"


@pytest.mark.asyncio
async def test_update_channel(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_upd", name="Original")
    )

    updated = await repo.update_channel(ch.id, ChannelUpdate(name="Updated", enabled=False))
    assert updated is not None
    assert updated.name == "Updated"
    assert updated.enabled is False


@pytest.mark.asyncio
async def test_update_channel_config_overrides(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_ucfg", name="CfgUpd")
    )

    updated = await repo.update_channel(
        ch.id, ChannelUpdate(config_overrides={"tags": ["new"]})
    )
    assert updated is not None
    assert updated.config_overrides is not None
    assert "new" in updated.config_overrides


@pytest.mark.asyncio
async def test_update_channel_not_found(repo: Repository) -> None:
    result = await repo.update_channel(9999, ChannelUpdate(name="X"))
    assert result is None


@pytest.mark.asyncio
async def test_delete_channel(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_del", name="Del")
    )

    deleted = await repo.delete_channel(ch.id)
    assert deleted is True

    assert await repo.get_channel(ch.id) is None


@pytest.mark.asyncio
async def test_delete_channel_not_found(repo: Repository) -> None:
    result = await repo.delete_channel(9999)
    assert result is False


@pytest.mark.asyncio
async def test_update_channel_checked(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_chk", name="Checked")
    )
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    await repo.update_channel_checked(ch.id, now)

    # Bulk update() doesn't refresh cached ORM objects; expunge to force re-fetch.
    repo._session.expunge(ch)
    refreshed = await repo.get_channel(ch.id)
    assert refreshed is not None
    assert refreshed.last_checked_at is not None


# ── Video CRUD ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_video(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_cv", name="VidCh")
    )
    meta = VideoMeta(youtube_id="yt_vid_1", title="Video 1", duration=120)
    vid = await repo.create_video(ch.id, meta)

    assert vid.id is not None
    assert vid.youtube_id == "yt_vid_1"
    assert vid.channel_id == ch.id
    assert vid.title == "Video 1"
    assert vid.duration == 120


@pytest.mark.asyncio
async def test_get_video_by_youtube_id(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_gvid", name="GVid")
    )
    meta = VideoMeta(youtube_id="yt_find_me", title="Find Me")
    await repo.create_video(ch.id, meta)

    found = await repo.get_video_by_youtube_id("yt_find_me")
    assert found is not None
    assert found.title == "Find Me"

    missing = await repo.get_video_by_youtube_id("yt_nonexistent")
    assert missing is None


@pytest.mark.asyncio
async def test_list_videos(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_lv", name="LVCh")
    )
    await repo.create_video(ch.id, VideoMeta(youtube_id="lv_1", title="V1"))
    await repo.create_video(ch.id, VideoMeta(youtube_id="lv_2", title="V2"))

    videos = await repo.list_videos(ch.id)
    assert len(videos) == 2


@pytest.mark.asyncio
async def test_list_videos_with_limit(repo: Repository) -> None:
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_lvl", name="LVL")
    )
    for i in range(5):
        await repo.create_video(ch.id, VideoMeta(youtube_id=f"lvl_{i}", title=f"V{i}"))

    videos = await repo.list_videos(ch.id, limit=3)
    assert len(videos) == 3


@pytest.mark.asyncio
async def test_list_videos_all_channels(repo: Repository) -> None:
    ch1 = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_ac1", name="AC1")
    )
    ch2 = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_ac2", name="AC2")
    )
    await repo.create_video(ch1.id, VideoMeta(youtube_id="ac_v1", title="V1"))
    await repo.create_video(ch2.id, VideoMeta(youtube_id="ac_v2", title="V2"))

    all_videos = await repo.list_videos()
    assert len(all_videos) == 2


# ── Task CRUD ───────────────────────────────────────────────────────────────


async def _create_video_for_task(repo: Repository, suffix: str = "") -> Video:
    """Helper to create a channel+video pair for task tests."""
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id=f"UC_task{suffix}", name=f"TaskCh{suffix}")
    )
    vid = await repo.create_video(
        ch.id, VideoMeta(youtube_id=f"task_vid{suffix}", title=f"TaskVid{suffix}")
    )
    return vid


@pytest.mark.asyncio
async def test_create_task(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_ct")
    task = await repo.create_task(vid.id)

    assert task.id is not None
    assert task.video_id == vid.id
    assert task.status == TaskStatus.PENDING
    assert task.priority == 0


@pytest.mark.asyncio
async def test_create_task_with_priority(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_cp")
    task = await repo.create_task(vid.id, priority=10)
    assert task.priority == 10


@pytest.mark.asyncio
async def test_get_task(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_gt")
    task = await repo.create_task(vid.id)

    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.id == task.id


@pytest.mark.asyncio
async def test_get_task_not_found(repo: Repository) -> None:
    result = await repo.get_task(9999)
    assert result is None


@pytest.mark.asyncio
async def test_list_tasks(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_lt")
    await repo.create_task(vid.id)
    await repo.create_task(vid.id)

    tasks = await repo.list_tasks()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_list_tasks_by_status(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_lts")
    t1 = await repo.create_task(vid.id)
    t2 = await repo.create_task(vid.id)
    await repo.update_task_status(t2.id, TaskStatus.DOWNLOADING)

    pending = await repo.list_tasks(status=TaskStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].id == t1.id

    downloading = await repo.list_tasks(status=TaskStatus.DOWNLOADING)
    assert len(downloading) == 1
    assert downloading[0].id == t2.id


@pytest.mark.asyncio
async def test_update_task_status(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_uts")
    task = await repo.create_task(vid.id)

    await repo.update_task_status(task.id, TaskStatus.DOWNLOADING, progress_pct=10.0)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.status == TaskStatus.DOWNLOADING
    assert fetched.progress_pct == 10.0


@pytest.mark.asyncio
async def test_update_task_status_with_error(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_utse")
    task = await repo.create_task(vid.id)

    await repo.update_task_status(
        task.id, TaskStatus.FAILED, error_message="Download timeout"
    )
    repo._session.expunge(task)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.status == TaskStatus.FAILED
    assert fetched.error_message == "Download timeout"


@pytest.mark.asyncio
async def test_update_task_status_transitions(repo: Repository) -> None:
    """Test a typical task lifecycle: PENDING → DOWNLOADING → SUBTITLING → UPLOADING → COMPLETED."""
    vid = await _create_video_for_task(repo, "_trans")
    task = await repo.create_task(vid.id)

    transitions: list[tuple[TaskStatus, float]] = [
        (TaskStatus.DOWNLOADING, 0.0),
        (TaskStatus.SUBTITLING, 33.0),
        (TaskStatus.UPLOADING, 66.0),
        (TaskStatus.COMPLETED, 100.0),
    ]
    for status, pct in transitions:
        await repo.update_task_status(task.id, status, progress_pct=pct)
        if task in repo._session:
            repo._session.expunge(task)
        fetched = await repo.get_task(task.id)
        assert fetched is not None
        assert fetched.status == status
        assert fetched.progress_pct == pct


@pytest.mark.asyncio
async def test_update_task_paths(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_utp")
    task = await repo.create_task(vid.id)

    await repo.update_task_paths(
        task.id,
        video_path="/tmp/video.mp4",
        subtitle_path="/tmp/sub.srt",
        subtitle_source="youtube_manual",
    )
    repo._session.expunge(task)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.video_path == "/tmp/video.mp4"
    assert fetched.subtitle_path == "/tmp/sub.srt"
    assert fetched.subtitle_source == SubtitleSource.YOUTUBE_MANUAL


@pytest.mark.asyncio
async def test_update_task_paths_no_values(repo: Repository) -> None:
    """Calling update_task_paths with no values is a no-op."""
    vid = await _create_video_for_task(repo, "_utpn")
    task = await repo.create_task(vid.id)

    # Should not raise
    await repo.update_task_paths(task.id)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.video_path is None


@pytest.mark.asyncio
async def test_update_task_bvid(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_bv")
    task = await repo.create_task(vid.id)

    await repo.update_task_bvid(task.id, "BV1234567890")
    repo._session.expunge(task)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.bilibili_bvid == "BV1234567890"


@pytest.mark.asyncio
async def test_increment_task_attempt(repo: Repository) -> None:
    vid = await _create_video_for_task(repo, "_inc")
    task = await repo.create_task(vid.id)
    assert task.attempt == 0

    await repo.increment_task_attempt(task.id)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.attempt == 1

    await repo.increment_task_attempt(task.id)
    fetched = await repo.get_task(task.id)
    assert fetched is not None
    assert fetched.attempt == 2


@pytest.mark.asyncio
async def test_increment_task_attempt_nonexistent(repo: Repository) -> None:
    """increment_task_attempt on a missing task is a no-op."""
    await repo.increment_task_attempt(9999)  # Should not raise


# ── BilibiliCredential CRUD ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_credential(repo: Repository) -> None:
    data = BilibiliCredentialCreate(
        label="main", sessdata="s1", bili_jct="j1", buvid3="b1"
    )
    cred = await repo.create_credential(data)

    assert cred.id is not None
    assert cred.label == "main"
    assert cred.sessdata == "s1"
    assert cred.is_active is True


@pytest.mark.asyncio
async def test_get_active_credential(repo: Repository) -> None:
    data = BilibiliCredentialCreate(
        label="active", sessdata="s", bili_jct="j", buvid3="b"
    )
    await repo.create_credential(data)

    active = await repo.get_active_credential()
    assert active is not None
    assert active.label == "active"


@pytest.mark.asyncio
async def test_get_active_credential_none(repo: Repository) -> None:
    result = await repo.get_active_credential()
    assert result is None


@pytest.mark.asyncio
async def test_list_credentials(repo: Repository) -> None:
    await repo.create_credential(
        BilibiliCredentialCreate(label="c1", sessdata="s", bili_jct="j", buvid3="b")
    )
    await repo.create_credential(
        BilibiliCredentialCreate(label="c2", sessdata="s", bili_jct="j", buvid3="b")
    )

    creds = await repo.list_credentials()
    assert len(creds) == 2


@pytest.mark.asyncio
async def test_delete_credential(repo: Repository) -> None:
    cred = await repo.create_credential(
        BilibiliCredentialCreate(label="del", sessdata="s", bili_jct="j", buvid3="b")
    )

    deleted = await repo.delete_credential(cred.id)
    assert deleted is True

    creds = await repo.list_credentials()
    assert len(creds) == 0


@pytest.mark.asyncio
async def test_delete_credential_not_found(repo: Repository) -> None:
    result = await repo.delete_credential(9999)
    assert result is False


@pytest.mark.asyncio
async def test_repo_commit(repo: Repository) -> None:
    """Repository.commit() should not raise."""
    ch = await repo.create_channel(
        ChannelCreate(youtube_channel_id="UC_commit", name="Commit")
    )
    await repo.commit()

    fetched = await repo.get_channel(ch.id)
    assert fetched is not None
