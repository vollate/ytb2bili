"""Tests for yt2bili.core.schemas Pydantic DTOs."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from yt2bili.core.enums import SubtitleSource, TaskStatus
from yt2bili.core.schemas import (
    BilibiliCredentialCreate,
    BilibiliCredentialOut,
    ChannelCreate,
    ChannelOut,
    ChannelUpdate,
    DownloadResult,
    TaskDetail,
    TaskSummary,
    UploadProgress,
    VideoMeta,
    VideoOut,
)


# ── ChannelCreate ───────────────────────────────────────────────────────────


class TestChannelCreate:
    def test_valid_minimal(self) -> None:
        cc = ChannelCreate(youtube_channel_id="UC_test", name="Test")
        assert cc.youtube_channel_id == "UC_test"
        assert cc.enabled is True
        assert cc.config_overrides is None

    def test_valid_with_all_fields(self) -> None:
        cc = ChannelCreate(
            youtube_channel_id="UC_full",
            name="Full",
            enabled=False,
            config_overrides={"quality": "720"},
        )
        assert cc.enabled is False
        assert cc.config_overrides == {"quality": "720"}

    def test_empty_youtube_channel_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChannelCreate(youtube_channel_id="", name="Test")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChannelCreate(youtube_channel_id="UC_test", name="")

    def test_too_long_youtube_channel_id(self) -> None:
        with pytest.raises(ValidationError):
            ChannelCreate(youtube_channel_id="x" * 65, name="Test")

    def test_too_long_name(self) -> None:
        with pytest.raises(ValidationError):
            ChannelCreate(youtube_channel_id="UC_test", name="x" * 257)


# ── ChannelUpdate ───────────────────────────────────────────────────────────


class TestChannelUpdate:
    def test_all_none_by_default(self) -> None:
        cu = ChannelUpdate()
        assert cu.name is None
        assert cu.enabled is None
        assert cu.config_overrides is None

    def test_partial_update(self) -> None:
        cu = ChannelUpdate(name="Updated")
        assert cu.name == "Updated"
        assert cu.enabled is None


# ── ChannelOut from_attributes ──────────────────────────────────────────────


class TestChannelOut:
    def test_from_attributes(self) -> None:
        """ChannelOut can be built from an ORM-like object."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)

        class FakeChannel:
            id = 1
            youtube_channel_id = "UC_fake"
            name = "Fake"
            enabled = True
            config_overrides = None
            last_checked_at = None
            created_at = now
            updated_at = now

        out = ChannelOut.model_validate(FakeChannel())
        assert out.id == 1
        assert out.youtube_channel_id == "UC_fake"
        assert out.created_at == now


# ── VideoMeta ───────────────────────────────────────────────────────────────


class TestVideoMeta:
    def test_valid_minimal(self) -> None:
        vm = VideoMeta(youtube_id="dQw4w9WgXcQ", title="Test Video")
        assert vm.youtube_id == "dQw4w9WgXcQ"
        assert vm.description is None
        assert vm.duration is None
        assert vm.youtube_upload_date is None
        assert vm.thumbnail_url is None

    def test_valid_with_all_fields(self) -> None:
        dt = datetime.datetime(2024, 1, 15, tzinfo=datetime.timezone.utc)
        vm = VideoMeta(
            youtube_id="abc123",
            title="Full",
            description="Desc",
            duration=120,
            youtube_upload_date=dt,
            thumbnail_url="https://img.youtube.com/thumb.jpg",
        )
        assert vm.duration == 120
        assert vm.youtube_upload_date == dt

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            VideoMeta(youtube_id="abc")  # type: ignore[call-arg]  # missing title


# ── VideoOut from_attributes ────────────────────────────────────────────────


class TestVideoOut:
    def test_from_attributes(self) -> None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)

        class FakeVideo:
            id = 10
            youtube_id = "yt_vid"
            channel_id = 1
            title = "Title"
            description = None
            duration = 300
            youtube_upload_date = None
            thumbnail_url = None
            created_at = now

        out = VideoOut.model_validate(FakeVideo())
        assert out.id == 10
        assert out.duration == 300


# ── TaskSummary ─────────────────────────────────────────────────────────────


class TestTaskSummary:
    def test_from_attributes(self) -> None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)

        class FakeTask:
            id = 5
            video_id = 2
            status = TaskStatus.DOWNLOADING
            priority = 3
            progress_pct = 45.0
            attempt = 1
            subtitle_source = SubtitleSource.YOUTUBE_AUTO
            bilibili_bvid = None
            error_message = None
            created_at = now
            updated_at = now

        ts = TaskSummary.model_validate(FakeTask())
        assert ts.id == 5
        assert ts.status == TaskStatus.DOWNLOADING
        assert ts.progress_pct == 45.0
        assert ts.subtitle_source == SubtitleSource.YOUTUBE_AUTO

    def test_serialization_round_trip(self) -> None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        ts = TaskSummary(
            id=1,
            video_id=1,
            status=TaskStatus.COMPLETED,
            priority=0,
            progress_pct=100.0,
            attempt=1,
            created_at=now,
            updated_at=now,
        )
        d = ts.model_dump()
        assert d["status"] == TaskStatus.COMPLETED
        assert d["progress_pct"] == 100.0

        ts2 = TaskSummary.model_validate(d)
        assert ts2 == ts


# ── TaskDetail ──────────────────────────────────────────────────────────────


class TestTaskDetail:
    def test_inherits_task_summary(self) -> None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        td = TaskDetail(
            id=1,
            video_id=1,
            status=TaskStatus.UPLOADING,
            priority=0,
            progress_pct=50.0,
            attempt=0,
            video_path="/tmp/v.mp4",
            subtitle_path="/tmp/s.srt",
            created_at=now,
            updated_at=now,
        )
        assert td.video_path == "/tmp/v.mp4"
        assert td.subtitle_path == "/tmp/s.srt"
        assert isinstance(td, TaskSummary)


# ── UploadProgress ──────────────────────────────────────────────────────────


class TestUploadProgress:
    def test_percent_normal(self) -> None:
        up = UploadProgress(uploaded_bytes=50, total_bytes=200)
        assert up.percent == 25.0

    def test_percent_complete(self) -> None:
        up = UploadProgress(uploaded_bytes=100, total_bytes=100)
        assert up.percent == 100.0

    def test_percent_zero_total(self) -> None:
        up = UploadProgress(uploaded_bytes=0, total_bytes=0)
        assert up.percent == 0.0

    def test_percent_zero_uploaded(self) -> None:
        up = UploadProgress(uploaded_bytes=0, total_bytes=500)
        assert up.percent == 0.0


# ── BilibiliCredentialCreate ────────────────────────────────────────────────


class TestBilibiliCredentialCreate:
    def test_valid(self) -> None:
        bc = BilibiliCredentialCreate(
            label="main", sessdata="s", bili_jct="j", buvid3="b"
        )
        assert bc.label == "main"
        assert bc.expires_at is None

    def test_empty_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BilibiliCredentialCreate(label="", sessdata="s", bili_jct="j", buvid3="b")

    def test_empty_sessdata_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BilibiliCredentialCreate(label="l", sessdata="", bili_jct="j", buvid3="b")


# ── BilibiliCredentialOut from_attributes ───────────────────────────────────


class TestBilibiliCredentialOut:
    def test_from_attributes(self) -> None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)

        class FakeCred:
            id = 1
            label = "test"
            is_active = True
            expires_at = None
            created_at = now

        out = BilibiliCredentialOut.model_validate(FakeCred())
        assert out.id == 1
        assert out.is_active is True


# ── DownloadResult ──────────────────────────────────────────────────────────


class TestDownloadResult:
    def test_defaults(self) -> None:
        dr = DownloadResult(video_path=Path("/tmp/video.mp4"))
        assert dr.subtitle_paths == []
        assert dr.subtitle_source == SubtitleSource.NONE

    def test_with_subtitles(self) -> None:
        dr = DownloadResult(
            video_path=Path("/tmp/v.mp4"),
            subtitle_paths=[Path("/tmp/s.srt")],
            subtitle_source=SubtitleSource.YOUTUBE_MANUAL,
        )
        assert len(dr.subtitle_paths) == 1
        assert dr.subtitle_source == SubtitleSource.YOUTUBE_MANUAL
