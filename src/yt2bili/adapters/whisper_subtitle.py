"""Whisper-based subtitle generator using *faster-whisper*."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from yt2bili.core.exceptions import SubtitleError

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    _HAS_FASTER_WHISPER = True
except ImportError:
    _HAS_FASTER_WHISPER = False

try:
    import srt as _srt  # type: ignore[import-untyped]
    import datetime as _dt

    _HAS_SRT = True
except ImportError:
    _HAS_SRT = False

# Common language codes supported by Whisper
_SUPPORTED_LANGUAGES: list[str] = [
    "en", "zh", "ja", "ko", "de", "fr", "es", "pt", "ru", "it",
    "nl", "pl", "tr", "sv", "ar", "hi", "th", "vi", "id", "uk",
]


class WhisperSubtitleGenerator:
    """Generate subtitles from audio using *faster-whisper*.

    Implements the :class:`~yt2bili.interfaces.subtitle_gen.SubtitleGenerator`
    protocol.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
    ) -> None:
        if not _HAS_FASTER_WHISPER:
            raise SubtitleError(
                "faster-whisper is not installed. "
                "Install it with: pip install 'yt2bili[whisper]'"
            )
        if not _HAS_SRT:
            raise SubtitleError(
                "srt library is not installed. "
                "Install it with: pip install srt"
            )
        self._model_size = model_size
        self._device = device
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        """Lazily initialise the Whisper model."""
        if self._model is None:
            self._model = WhisperModel(
                self._model_size, device=self._device
            )
        return self._model

    async def generate(
        self,
        media_path: Path,
        language: str,
        output_path: Path,
    ) -> Path:
        """Transcribe *media_path* and write an SRT file to *output_path*.

        The heavy transcription work runs in a thread pool so the event
        loop remains responsive.
        """
        srt_text = await asyncio.to_thread(
            self._transcribe, media_path, language
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(srt_text, encoding="utf-8")
        return output_path

    def supported_languages(self) -> list[str]:
        """Return commonly supported Whisper language codes."""
        return list(_SUPPORTED_LANGUAGES)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transcribe(self, media_path: Path, language: str) -> str:
        """Run transcription synchronously and return SRT-formatted text."""
        model = self._get_model()
        segments_iter, _info = model.transcribe(
            str(media_path), language=language
        )

        srt_subs: list[_srt.Subtitle] = []
        for idx, seg in enumerate(segments_iter, start=1):
            srt_subs.append(
                _srt.Subtitle(
                    index=idx,
                    start=_dt.timedelta(seconds=seg.start),
                    end=_dt.timedelta(seconds=seg.end),
                    content=seg.text.strip(),
                )
            )

        return _srt.compose(srt_subs)
