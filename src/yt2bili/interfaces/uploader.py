"""Abstract uploader protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from yt2bili.core.schemas import UploadProgress


@runtime_checkable
class UploaderBackend(Protocol):
    """Protocol for video upload backends (e.g. Bilibili)."""

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Validate credentials. Return True if valid."""
        ...

    async def upload(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        partition_id: int,
        thumbnail_path: Path | None = None,
        source_url: str = "",
    ) -> str:
        """Upload a video. Return the platform video ID (e.g. BVid)."""
        ...

    def progress(self) -> AsyncIterator[UploadProgress]:
        """Yield upload progress events."""
        ...
