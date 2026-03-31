"""Application configuration loaded from YAML and validated via Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from yt2bili.core.enums import VideoQuality
from yt2bili.core.exceptions import ConfigError
from yt2bili.core.paths import default_db_url, default_download_dir


# ── Sub‑configs ──────────────────────────────────────────────────────────────


class ScheduleConfig(BaseModel):
    """Scheduler / polling settings."""

    poll_interval_minutes: int = Field(default=15, ge=1)
    max_concurrent_downloads: int = Field(default=2, ge=1)
    max_concurrent_uploads: int = Field(default=1, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_base: float = Field(default=2.0, gt=0)


class DownloadConfig(BaseModel):
    """Download quality and subtitle language preferences."""

    quality: VideoQuality = VideoQuality.BEST
    subtitle_langs: list[str] = Field(default_factory=lambda: ["zh-Hans", "en", "ja"])
    download_dir: Path = Field(default_factory=default_download_dir)


class SubtitleConfig(BaseModel):
    """Subtitle generation settings."""

    subtitle_generator: str = "none"  # "whisper" | "cloud" | "none"
    whisper_model: str = "base"
    whisper_device: str = "auto"
    subtitle_fallback_generate: bool = True


class UploadConfig(BaseModel):
    """Bilibili upload defaults."""

    bilibili_tid: int = Field(default=17, description="Bilibili partition / tid")
    tags: list[str] = Field(default_factory=lambda: ["搬运", "YouTube"])
    title_template: str = "{original_title}"
    desc_template: str = "搬运自YouTube: {youtube_url}\n\n{original_description}"
    copyright: int = Field(default=2, description="2=repost")
    delete_after_upload: bool = False


class WebUIConfig(BaseModel):
    """NiceGUI web server settings."""

    host: str = "127.0.0.1"
    port: int = 8080
    secret: str = "change-me"
    language: str = "en"


class ProxyConfig(BaseModel):
    """Network proxy settings."""

    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: str | None = None

    def to_httpx_proxy(self) -> str | None:
        """Return a single proxy URL for ``httpx.AsyncClient(proxy=...)``.

        httpx ≥ 0.28 uses ``proxy=`` (single URL) instead of the old
        ``proxies=`` dict.  Returns ``None`` when no proxy is configured.
        """
        return self.https_proxy or self.http_proxy

    def to_ytdlp_proxy(self) -> str | None:
        """Return the proxy string for yt-dlp's ``proxy`` option.

        Prefers ``https_proxy``, falls back to ``http_proxy``.
        Returns ``None`` when no proxy is configured.
        """
        return self.https_proxy or self.http_proxy


class NotifyConfig(BaseModel):
    """Notification settings."""

    webhook_url: str | None = None
    notify_on: list[str] = Field(default_factory=lambda: ["completed", "failed"])


# ── Channel‑level override ───────────────────────────────────────────────────


class ChannelConfig(BaseModel):
    """Per‑channel config overrides (all fields optional)."""

    quality: VideoQuality | None = None
    subtitle_langs: list[str] | None = None
    bilibili_tid: int | None = None
    tags: list[str] | None = None
    title_template: str | None = None
    desc_template: str | None = None
    enabled: bool | None = None


# ── Root config ──────────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    """Root application configuration."""

    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    subtitle: SubtitleConfig = Field(default_factory=SubtitleConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    webui: WebUIConfig = Field(default_factory=WebUIConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    database_url: str = Field(default_factory=default_db_url)


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate configuration from a YAML file.

    If *path* is ``None``, returns an ``AppConfig`` with all defaults.
    """
    if path is None:
        return AppConfig()
    try:
        text = path.expanduser().read_text(encoding="utf-8")
        raw: dict[str, Any] = yaml.safe_load(text) or {}
        return AppConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"Failed to load config from {path}: {exc}") from exc
