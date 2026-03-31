"""Cloud-based subtitle generator – placeholder for future implementation."""

from __future__ import annotations

from pathlib import Path


class CloudSubtitleGenerator:
    """Placeholder cloud subtitle generator.

    Implements the :class:`~yt2bili.interfaces.subtitle_gen.SubtitleGenerator`
    protocol surface but raises :class:`NotImplementedError` for all
    operations.  A concrete implementation can be swapped in when a
    cloud transcription provider (e.g. Google Speech-to-Text, AWS
    Transcribe) is integrated.
    """

    async def generate(
        self,
        media_path: Path,
        language: str,
        output_path: Path,
    ) -> Path:
        """Not implemented – raises :class:`NotImplementedError`."""
        raise NotImplementedError(
            "CloudSubtitleGenerator is not yet implemented. "
            "Configure a different subtitle_generator in your config "
            "(e.g. 'whisper') or disable subtitle fallback generation."
        )

    def supported_languages(self) -> list[str]:
        """Return an empty list – no languages supported yet."""
        return []
