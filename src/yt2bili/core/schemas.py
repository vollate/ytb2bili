"""Pydantic DTOs / schemas for yt2bili."""

from __future__ import annotations

import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from yt2bili.core.enums import SubtitleSource, TaskStatus


# ── Channel ──────────────────────────────────────────────────────────────────


class ChannelCreate(BaseModel):
    """Input schema for creating a new monitored channel."""

    youtube_channel_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    enabled: bool = True
    config_overrides: dict[str, object] | None = None


class ChannelUpdate(BaseModel):
    """Input schema for updating a channel."""

    name: str | None = None
    enabled: bool | None = None
    config_overrides: dict[str, object] | None = None


class ChannelOut(BaseModel):
    """Output schema for channel responses."""

    model_config = {"from_attributes": True}

    id: int
    youtube_channel_id: str
    name: str
    enabled: bool
    avatar_url: str | None = None
    config_overrides: str | None = None
    last_checked_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ── Video ────────────────────────────────────────────────────────────────────


class VideoMeta(BaseModel):
    """Metadata extracted from a YouTube video (RSS / yt-dlp)."""

    youtube_id: str
    title: str
    description: str | None = None
    duration: int | None = None
    youtube_upload_date: datetime.datetime | None = None
    thumbnail_url: str | None = None


class VideoOut(BaseModel):
    """Output schema for video responses."""

    model_config = {"from_attributes": True}

    id: int
    youtube_id: str
    channel_id: int
    title: str
    description: str | None = None
    duration: int | None = None
    youtube_upload_date: datetime.datetime | None = None
    thumbnail_url: str | None = None
    created_at: datetime.datetime


# ── Task ─────────────────────────────────────────────────────────────────────


class TaskSummary(BaseModel):
    """Lightweight task info for listing."""

    model_config = {"from_attributes": True}

    id: int
    video_id: int
    status: TaskStatus
    priority: int
    progress_pct: float
    attempt: int
    subtitle_source: SubtitleSource | None = None
    bilibili_bvid: str | None = None
    error_message: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class TaskDetail(TaskSummary):
    """Full task detail including paths."""

    video_path: str | None = None
    subtitle_path: str | None = None


# ── Upload progress ──────────────────────────────────────────────────────────


class UploadProgress(BaseModel):
    """Progress event emitted during upload."""

    uploaded_bytes: int
    total_bytes: int

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.uploaded_bytes / self.total_bytes) * 100.0


# ── Bilibili Credential ─────────────────────────────────────────────────────


class BilibiliCredentialCreate(BaseModel):
    """Input schema for adding a Bilibili credential."""

    label: str = Field(..., min_length=1, max_length=128)
    sessdata: str = Field(..., min_length=1)
    bili_jct: str = Field(..., min_length=1)
    buvid3: str = Field(..., min_length=1)
    expires_at: datetime.datetime | None = None


class BilibiliCredentialOut(BaseModel):
    """Output schema for Bilibili credential (no secrets)."""

    model_config = {"from_attributes": True}

    id: int
    label: str
    is_active: bool
    expires_at: datetime.datetime | None = None
    created_at: datetime.datetime


# ── Download result ──────────────────────────────────────────────────────────


class DownloadResult(BaseModel):
    """Result of downloading a video."""

    video_path: Path
    subtitle_paths: list[Path] = Field(default_factory=list)
    subtitle_source: SubtitleSource = SubtitleSource.NONE
