"""Tests for yt2bili.services.subtitle."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import SubtitleSource
from yt2bili.core.exceptions import SubtitleError
from yt2bili.services.subtitle import SubtitleService


# ── Helpers ─────────────────────────────────────────────────────────────────


class FakeGenerator:
    """Fake SubtitleGenerator for testing the fallback chain."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.called = False

    async def generate(
        self, media_path: Path, language: str, output_path: Path
    ) -> Path:
        self.called = True
        if self._fail:
            raise RuntimeError("generation failed")
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        return output_path

    def supported_languages(self) -> list[str]:
        return ["en", "zh"]


def _make_srt(path: Path) -> Path:
    """Write a minimal SRT file and return its path."""
    path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
    )
    return path


def _make_vtt(path: Path) -> Path:
    """Write a minimal WebVTT file and return its path."""
    path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n", encoding="utf-8"
    )
    return path


# ── Fallback chain tests ───────────────────────────────────────────────────


class TestSubtitleFallbackChain:
    """Verify the three-tier fallback: YT subs → generate → None."""

    @pytest.mark.asyncio()
    async def test_youtube_subs_used_directly(self, tmp_path: Path) -> None:
        """When YouTube subtitles exist, use them (convert if needed)."""
        srt = _make_srt(tmp_path / "video.en.srt")
        video = tmp_path / "video.mp4"
        video.touch()

        svc = SubtitleService(AppConfig(), generator=None)
        path, source = await svc.process(
            video_path=video,
            subtitle_paths=[srt],
            subtitle_source=SubtitleSource.YOUTUBE_MANUAL,
            language="en",
        )

        assert path == srt
        assert source == SubtitleSource.YOUTUBE_MANUAL

    @pytest.mark.asyncio()
    async def test_vtt_converted_to_srt(self, tmp_path: Path) -> None:
        """Non-SRT subtitles should be converted via pysubs2."""
        vtt = _make_vtt(tmp_path / "video.en.vtt")
        video = tmp_path / "video.mp4"
        video.touch()

        svc = SubtitleService(AppConfig(), generator=None)
        path, source = await svc.process(
            video_path=video,
            subtitle_paths=[vtt],
            subtitle_source=SubtitleSource.YOUTUBE_AUTO,
            language="en",
        )

        assert path is not None
        assert path.suffix == ".srt"
        assert source == SubtitleSource.YOUTUBE_AUTO

    @pytest.mark.asyncio()
    async def test_fallback_to_generator(self, tmp_path: Path) -> None:
        """No YT subs + generator available → generate subtitles."""
        video = tmp_path / "video.mp4"
        video.touch()

        gen = FakeGenerator()
        svc = SubtitleService(AppConfig(), generator=gen)
        path, source = await svc.process(
            video_path=video,
            subtitle_paths=[],
            subtitle_source=SubtitleSource.NONE,
            language="en",
        )

        assert gen.called
        assert path is not None
        assert source == SubtitleSource.GENERATED

    @pytest.mark.asyncio()
    async def test_no_generator_returns_none(self, tmp_path: Path) -> None:
        """No YT subs + no generator → (None, NONE)."""
        video = tmp_path / "video.mp4"
        video.touch()

        svc = SubtitleService(AppConfig(), generator=None)
        path, source = await svc.process(
            video_path=video,
            subtitle_paths=[],
            subtitle_source=SubtitleSource.NONE,
            language="en",
        )

        assert path is None
        assert source == SubtitleSource.NONE

    @pytest.mark.asyncio()
    async def test_fallback_disabled(self, tmp_path: Path) -> None:
        """Fallback generation disabled in config → (None, NONE)."""
        video = tmp_path / "video.mp4"
        video.touch()

        config = AppConfig()
        config.subtitle.subtitle_fallback_generate = False

        gen = FakeGenerator()
        svc = SubtitleService(config, generator=gen)
        path, source = await svc.process(
            video_path=video,
            subtitle_paths=[],
            subtitle_source=SubtitleSource.NONE,
            language="en",
        )

        assert not gen.called
        assert path is None
        assert source == SubtitleSource.NONE


# ── Error handling ──────────────────────────────────────────────────────────


class TestSubtitleErrors:
    """Errors during processing should raise SubtitleError."""

    @pytest.mark.asyncio()
    async def test_generation_error_wrapped(self, tmp_path: Path) -> None:
        """Generator failure should be wrapped in SubtitleError."""
        video = tmp_path / "video.mp4"
        video.touch()

        gen = FakeGenerator(fail=True)
        svc = SubtitleService(AppConfig(), generator=gen)

        with pytest.raises(SubtitleError, match="generation failed"):
            await svc.process(
                video_path=video,
                subtitle_paths=[],
                subtitle_source=SubtitleSource.NONE,
                language="en",
            )


# ── Progress callback ──────────────────────────────────────────────────────


class TestProgressCallback:
    """Progress should be reported in the 40-60% range."""

    @pytest.mark.asyncio()
    async def test_progress_reported(self, tmp_path: Path) -> None:
        srt = _make_srt(tmp_path / "video.en.srt")
        video = tmp_path / "video.mp4"
        video.touch()

        reported: list[float] = []

        async def cb(pct: float) -> None:
            reported.append(pct)

        svc = SubtitleService(AppConfig(), generator=None)
        await svc.process(
            video_path=video,
            subtitle_paths=[srt],
            subtitle_source=SubtitleSource.YOUTUBE_MANUAL,
            language="en",
            progress_callback=cb,
        )

        assert len(reported) >= 1
        for pct in reported:
            assert 40.0 <= pct <= 60.0
