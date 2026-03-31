"""Abstract subtitle generator protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SubtitleGenerator(Protocol):
    """Protocol for subtitle generation backends."""

    async def generate(
        self, media_path: Path, language: str, output_path: Path
    ) -> Path:
        """Generate subtitles for *media_path* and write to *output_path*.

        Returns the path to the generated subtitle file.
        """
        ...

    def supported_languages(self) -> list[str]:
        """Return list of supported language codes."""
        ...
