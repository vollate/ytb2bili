"""Enumerations for yt2bili domain model."""

from enum import Enum


class TaskStatus(str, Enum):
    """Lifecycle states for a video processing task."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    SUBTITLING = "subtitling"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class SubtitleSource(str, Enum):
    """Where the subtitle came from."""

    YOUTUBE_MANUAL = "youtube_manual"
    YOUTUBE_AUTO = "youtube_auto"
    GENERATED = "generated"
    NONE = "none"


class VideoQuality(str, Enum):
    """Preferred video download quality."""

    BEST = "best"
    Q1080 = "1080"
    Q720 = "720"
    Q480 = "480"
