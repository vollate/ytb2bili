"""Tests for yt2bili.core.config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2bili.core.config import (
    AppConfig,
    ChannelConfig,
    DownloadConfig,
    ProxyConfig,
    ScheduleConfig,
    SubtitleConfig,
    UploadConfig,
    WebUIConfig,
    load_config,
)
from yt2bili.core.enums import VideoQuality
from yt2bili.core.exceptions import ConfigError
from yt2bili.core.paths import default_db_url, default_download_dir


# ── AppConfig defaults ──────────────────────────────────────────────────────


def test_app_config_all_defaults() -> None:
    """AppConfig() provides sensible defaults for every sub-config."""
    cfg = AppConfig()

    assert cfg.schedule.poll_interval_minutes == 15
    assert cfg.schedule.max_concurrent_downloads == 2
    assert cfg.schedule.max_concurrent_uploads == 1
    assert cfg.schedule.max_retries == 3
    assert cfg.schedule.retry_backoff_base == 2.0

    assert cfg.download.quality == VideoQuality.BEST
    assert cfg.download.subtitle_langs == ["zh-Hans", "en", "ja"]
    assert cfg.download.download_dir == default_download_dir()

    assert cfg.subtitle.subtitle_generator == "none"
    assert cfg.subtitle.whisper_model == "base"
    assert cfg.subtitle.subtitle_fallback_generate is True

    assert cfg.upload.bilibili_tid == 17
    assert cfg.upload.tags == ["搬运", "YouTube"]
    assert cfg.upload.copyright == 2
    assert cfg.upload.delete_after_upload is False

    assert cfg.webui.host == "127.0.0.1"
    assert cfg.webui.port == 8080

    assert cfg.notify.webhook_url is None
    assert cfg.notify.notify_on == ["completed", "failed"]

    assert cfg.proxy.http_proxy is None
    assert cfg.proxy.https_proxy is None
    assert cfg.proxy.no_proxy is None

    assert "sqlite" in cfg.database_url


# ── load_config ─────────────────────────────────────────────────────────────


def test_load_config_none_returns_defaults() -> None:
    """load_config(None) returns default AppConfig."""
    cfg = load_config(None)
    assert cfg == AppConfig()


def test_load_config_from_yaml(tmp_path: Path) -> None:
    """load_config reads a YAML file and merges with defaults."""
    yaml_content = """\
schedule:
  poll_interval_minutes: 30
  max_retries: 5
download:
  quality: "1080"
  subtitle_langs:
    - "en"
upload:
  tags:
    - "test"
  delete_after_upload: true
database_url: "sqlite+aiosqlite:///custom.db"
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(cfg_file)

    assert cfg.schedule.poll_interval_minutes == 30
    assert cfg.schedule.max_retries == 5
    # Non-overridden defaults should remain
    assert cfg.schedule.max_concurrent_downloads == 2

    assert cfg.download.quality == VideoQuality.Q1080
    assert cfg.download.subtitle_langs == ["en"]

    assert cfg.upload.tags == ["test"]
    assert cfg.upload.delete_after_upload is True
    # Non-overridden upload defaults
    assert cfg.upload.bilibili_tid == 17

    assert cfg.database_url == "sqlite+aiosqlite:///custom.db"


def test_load_config_empty_yaml(tmp_path: Path) -> None:
    """An empty YAML file returns all defaults."""
    cfg_file = tmp_path / "empty.yaml"
    cfg_file.write_text("", encoding="utf-8")

    cfg = load_config(cfg_file)
    assert cfg == AppConfig()


def test_load_config_partial_yaml(tmp_path: Path) -> None:
    """A YAML file with only one section set leaves others at defaults."""
    yaml_content = """\
webui:
  port: 9090
"""
    cfg_file = tmp_path / "partial.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(cfg_file)
    assert cfg.webui.port == 9090
    assert cfg.webui.host == "127.0.0.1"  # default
    assert cfg.schedule == ScheduleConfig()


def test_load_config_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    """Malformed YAML file raises ConfigError."""
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text("schedule:\n  poll_interval_minutes: not_an_int\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Failed to load config"):
        load_config(cfg_file)


def test_load_config_nonexistent_file_raises_config_error() -> None:
    """A path to a missing file raises ConfigError."""
    with pytest.raises(ConfigError, match="Failed to load config"):
        load_config(Path("/nonexistent/config.yaml"))


def test_load_config_invalid_schedule_value(tmp_path: Path) -> None:
    """Validation error (e.g. poll_interval_minutes < 1) raises ConfigError."""
    yaml_content = """\
schedule:
  poll_interval_minutes: 0
"""
    cfg_file = tmp_path / "invalid_sched.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(cfg_file)


# ── ChannelConfig partial overrides ─────────────────────────────────────────


def test_channel_config_all_none_by_default() -> None:
    """ChannelConfig() has all fields as None."""
    cc = ChannelConfig()
    assert cc.quality is None
    assert cc.subtitle_langs is None
    assert cc.bilibili_tid is None
    assert cc.tags is None
    assert cc.title_template is None
    assert cc.desc_template is None
    assert cc.enabled is None


def test_channel_config_partial_override() -> None:
    """ChannelConfig can set specific overrides while leaving others None."""
    cc = ChannelConfig(quality=VideoQuality.Q720, tags=["override"])
    assert cc.quality == VideoQuality.Q720
    assert cc.tags == ["override"]
    assert cc.subtitle_langs is None
    assert cc.enabled is None


def test_channel_config_from_dict() -> None:
    """ChannelConfig can be built from a raw dict (like JSON config_overrides)."""
    raw = {"quality": "480", "bilibili_tid": 42, "enabled": False}
    cc = ChannelConfig.model_validate(raw)
    assert cc.quality == VideoQuality.Q480
    assert cc.bilibili_tid == 42
    assert cc.enabled is False
    assert cc.tags is None


# ── Sub-config validation ───────────────────────────────────────────────────


def test_schedule_config_min_values() -> None:
    """ScheduleConfig enforces ge/gt constraints."""
    with pytest.raises(ValueError):
        ScheduleConfig(poll_interval_minutes=0)
    with pytest.raises(ValueError):
        ScheduleConfig(max_concurrent_downloads=0)
    with pytest.raises(ValueError):
        ScheduleConfig(retry_backoff_base=0)


def test_download_config_quality_enum() -> None:
    """DownloadConfig.quality accepts string values for the enum."""
    dc = DownloadConfig(quality="720")  # type: ignore[arg-type]
    assert dc.quality == VideoQuality.Q720


# ── ProxyConfig ──────────────────────────────────────────────────────────────


class TestProxyConfig:
    """Tests for ProxyConfig helper methods."""

    def test_defaults_are_none(self) -> None:
        pc = ProxyConfig()
        assert pc.http_proxy is None
        assert pc.https_proxy is None
        assert pc.no_proxy is None

    def test_to_httpx_proxy_returns_none_when_unset(self) -> None:
        assert ProxyConfig().to_httpx_proxy() is None

    def test_to_httpx_proxy_http_only(self) -> None:
        pc = ProxyConfig(http_proxy="http://proxy:8080")
        assert pc.to_httpx_proxy() == "http://proxy:8080"

    def test_to_httpx_proxy_both_prefers_https(self) -> None:
        pc = ProxyConfig(
            http_proxy="http://proxy:8080",
            https_proxy="http://secure-proxy:8443",
        )
        assert pc.to_httpx_proxy() == "http://secure-proxy:8443"

    def test_to_httpx_proxy_https_only(self) -> None:
        pc = ProxyConfig(https_proxy="http://secure:443")
        assert pc.to_httpx_proxy() == "http://secure:443"

    def test_to_ytdlp_proxy_returns_none_when_unset(self) -> None:
        assert ProxyConfig().to_ytdlp_proxy() is None

    def test_to_ytdlp_proxy_prefers_https(self) -> None:
        pc = ProxyConfig(
            http_proxy="http://a:80",
            https_proxy="http://b:443",
        )
        assert pc.to_ytdlp_proxy() == "http://b:443"

    def test_to_ytdlp_proxy_falls_back_to_http(self) -> None:
        pc = ProxyConfig(http_proxy="http://a:80")
        assert pc.to_ytdlp_proxy() == "http://a:80"

    def test_proxy_config_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
proxy:
  http_proxy: "http://myproxy:3128"
  https_proxy: "http://myproxy:3129"
  no_proxy: "localhost,127.0.0.1"
"""
        cfg_file = tmp_path / "proxy.yaml"
        cfg_file.write_text(yaml_content, encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.proxy.http_proxy == "http://myproxy:3128"
        assert cfg.proxy.https_proxy == "http://myproxy:3129"
        assert cfg.proxy.no_proxy == "localhost,127.0.0.1"
