"""SQLAlchemy ORM models for yt2bili."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from yt2bili.core.enums import SubtitleSource, TaskStatus


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Channel(Base):
    """A monitored YouTube channel."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    config_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    videos: Mapped[list[Video]] = relationship("Video", back_populates="channel", lazy="selectin")

    def get_config_overrides(self) -> dict[str, Any]:
        """Parse JSON config_overrides field."""
        import json

        if self.config_overrides is None:
            return {}
        result: dict[str, Any] = json.loads(self.config_overrides)
        return result

    def set_config_overrides(self, overrides: dict[str, Any]) -> None:
        """Serialize config_overrides to JSON."""
        import json

        self.config_overrides = json.dumps(overrides) if overrides else None


class Video(Base):
    """A YouTube video discovered by monitoring."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    youtube_upload_date: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    channel: Mapped[Channel] = relationship("Channel", back_populates="videos")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="video", lazy="selectin")


class Task(Base):
    """A video processing task through the pipeline."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("videos.id"), nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subtitle_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subtitle_source: Mapped[SubtitleSource | None] = mapped_column(
        Enum(SubtitleSource), nullable=True
    )
    bilibili_bvid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    video: Mapped[Video] = relationship("Video", back_populates="tasks")


class BilibiliCredential(Base):
    """Stored Bilibili authentication credentials."""

    __tablename__ = "bilibili_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    sessdata: Mapped[str] = mapped_column(String(512), nullable=False)
    bili_jct: Mapped[str] = mapped_column(String(512), nullable=False)
    buvid3: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
