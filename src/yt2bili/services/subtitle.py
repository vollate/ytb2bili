"""Subtitle processing service – convert, fallback-generate, or skip."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import pysubs2

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import SubtitleSource
from yt2bili.core.exceptions import SubtitleError
from yt2bili.interfaces.subtitle_gen import SubtitleGenerator

logger = logging.getLogger(__name__)

# Progress range for the subtitle phase: 40% – 60%
_PROGRESS_MIN = 40.0
_PROGRESS_MAX = 60.0


class SubtitleService:
    """Process (convert / generate) subtitles for a downloaded video.

    Follows a fallback chain:
    1. If YouTube subtitles exist → convert to SRT if necessary.
    2. If no YT subs and a :class:`SubtitleGenerator` is available and
       ``subtitle_fallback_generate`` is enabled → generate.
    3. Otherwise → ``(None, SubtitleSource.NONE)``.
    """

    def __init__(
        self,
        config: AppConfig,
        generator: SubtitleGenerator | None = None,
    ) -> None:
        self._config = config
        self._generator = generator

    async def process(
        self,
        video_path: Path,
        subtitle_paths: list[Path],
        subtitle_source: SubtitleSource,
        language: str,
        progress_callback: Callable[[float], Awaitable[None]] | None = None,
    ) -> tuple[Path | None, SubtitleSource]:
        """Process subtitles through the fallback chain.

        Parameters
        ----------
        video_path:
            Path to the downloaded video file.
        subtitle_paths:
            Subtitle files obtained during download (may be empty).
        subtitle_source:
            How the subtitles were obtained during download.
        language:
            Preferred subtitle language code.
        progress_callback:
            Optional async callable receiving a float in ``[40, 60]``.

        Returns
        -------
        tuple[Path | None, SubtitleSource]
            The final subtitle path (or ``None``) and its source.
        """
        await self._report(progress_callback, 0.0)

        # ── 1. YouTube subtitles exist ──────────────────────────────
        if subtitle_paths:
            try:
                srt_path = self._convert_to_srt(subtitle_paths[0])
                await self._report(progress_callback, 1.0)
                return srt_path, subtitle_source
            except Exception as exc:
                raise SubtitleError(
                    f"Failed to convert subtitle: {exc}"
                ) from exc

        # ── 2. Fallback generation ──────────────────────────────────
        if (
            self._generator is not None
            and self._config.subtitle.subtitle_fallback_generate
        ):
            await self._report(progress_callback, 0.2)
            try:
                output_path = video_path.with_suffix(".srt")
                generated = await self._generator.generate(
                    media_path=video_path,
                    language=language,
                    output_path=output_path,
                )
                await self._report(progress_callback, 1.0)
                return generated, SubtitleSource.GENERATED
            except Exception as exc:
                raise SubtitleError(
                    f"Subtitle generation failed: {exc}"
                ) from exc

        # ── 3. Nothing available ────────────────────────────────────
        await self._report(progress_callback, 1.0)
        return None, SubtitleSource.NONE

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_to_srt(sub_path: Path) -> Path:
        """Convert a subtitle file to ``.srt`` using *pysubs2*.

        If the file is already ``.srt`` it is returned as-is.
        """
        if sub_path.suffix.lower() == ".srt":
            return sub_path

        subs = pysubs2.load(str(sub_path))
        srt_path = sub_path.with_suffix(".srt")
        subs.save(str(srt_path), format_="srt")
        return srt_path

    @staticmethod
    async def _report(
        callback: Callable[[float], Awaitable[None]] | None,
        fraction: float,
    ) -> None:
        """Map *fraction* (0-1) into the 40-60% progress range and report."""
        if callback is not None:
            mapped = _PROGRESS_MIN + fraction * (_PROGRESS_MAX - _PROGRESS_MIN)
            await callback(mapped)
