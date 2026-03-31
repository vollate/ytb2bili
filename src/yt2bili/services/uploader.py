"""Upload service – orchestrates video uploads via an injected backend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from yt2bili.core.config import AppConfig, ChannelConfig
from yt2bili.core.exceptions import UploadError
from yt2bili.core.models import Channel, Task, Video
from yt2bili.interfaces.uploader import UploaderBackend

log: structlog.stdlib.BoundLogger = structlog.get_logger()

# Upload progress is mapped to the 60-95 % range of overall task progress.
_UPLOAD_PROGRESS_MIN: float = 60.0
_UPLOAD_PROGRESS_MAX: float = 95.0


class UploadService:
    """High-level upload orchestrator.

    Resolves templates, merges per-channel overrides, authenticates with the
    active credential, and delegates the actual upload to *backend*.
    """

    def __init__(self, backend: UploaderBackend, config: AppConfig) -> None:
        self._backend = backend
        self._config = config

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_channel_config(
        config: AppConfig, channel: Channel
    ) -> ChannelConfig:
        """Merge per-channel overrides into a ``ChannelConfig``."""
        overrides: dict[str, Any] = channel.get_config_overrides()
        if not overrides:
            return ChannelConfig()
        return ChannelConfig.model_validate(overrides)

    def _build_title(self, video: Video, channel_cfg: ChannelConfig) -> str:
        template = channel_cfg.title_template or self._config.upload.title_template
        return template.format(original_title=video.title)

    def _build_description(
        self, video: Video, channel_cfg: ChannelConfig
    ) -> str:
        template = channel_cfg.desc_template or self._config.upload.desc_template
        youtube_url = f"https://www.youtube.com/watch?v={video.youtube_id}"
        return template.format(
            youtube_url=youtube_url,
            original_description=video.description or "",
        )

    def _get_tags(self, channel_cfg: ChannelConfig) -> list[str]:
        return channel_cfg.tags or self._config.upload.tags

    def _get_tid(self, channel_cfg: ChannelConfig) -> int:
        return channel_cfg.bilibili_tid or self._config.upload.bilibili_tid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_video(
        self,
        task: Task,
        video: Video,
        channel: Channel,
        video_path: Path,
        subtitle_path: Path | None,
        progress_callback: Callable[[float], Awaitable[None]] | None = None,
    ) -> str:
        """Upload *video_path* to Bilibili and return the BVid.

        Parameters
        ----------
        task:
            The current processing task (used for context / logging).
        video:
            The ``Video`` ORM instance with YouTube metadata.
        channel:
            The ``Channel`` ORM instance (carries config overrides).
        video_path:
            Local path to the downloaded video file.
        subtitle_path:
            Optional path to a subtitle file to include.
        progress_callback:
            Optional async callable receiving overall progress (0-100 %).
            Upload progress is mapped to the 60-95 % range.

        Raises
        ------
        UploadError
            On authentication or upload failures.
        """
        channel_cfg = self._resolve_channel_config(self._config, channel)

        title = self._build_title(video, channel_cfg)
        description = self._build_description(video, channel_cfg)
        tags = self._get_tags(channel_cfg)
        tid = self._get_tid(channel_cfg)
        source_url = f"https://www.youtube.com/watch?v={video.youtube_id}"

        log.info(
            "upload.start",
            task_id=task.id,
            video_id=video.youtube_id,
            title=title,
        )

        # -- Authenticate --------------------------------------------------
        try:
            credential = _extract_credential(task)
            authenticated = await self._backend.authenticate(credential)
            if not authenticated:
                raise UploadError("Backend rejected the provided credentials")
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Authentication failed: {exc}") from exc

        # -- Upload --------------------------------------------------------
        try:
            bvid = await self._backend.upload(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                partition_id=tid,
                thumbnail_path=None,
                source_url=source_url,
            )
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Upload failed: {exc}") from exc

        # -- Stream progress (best-effort) ---------------------------------
        if progress_callback is not None:
            try:
                async for event in self._backend.progress():
                    pct = event.percent  # 0-100
                    mapped = _UPLOAD_PROGRESS_MIN + (
                        pct / 100.0
                    ) * (_UPLOAD_PROGRESS_MAX - _UPLOAD_PROGRESS_MIN)
                    await progress_callback(mapped)
            except Exception:
                log.debug("upload.progress_stream_ended", task_id=task.id)

        log.info("upload.done", task_id=task.id, bvid=bvid)
        return bvid


# ------------------------------------------------------------------
# Module-private helpers
# ------------------------------------------------------------------


def _extract_credential(task: Task) -> dict[str, str]:
    """Build a credential dict expected by ``UploaderBackend.authenticate``.

    In a real deployment the active credential would be looked up from the
    database.  Here the task's video → channel path is used only for logging;
    the caller is expected to have ensured an active credential exists.

    For now we raise ``UploadError`` if the credential cannot be determined.
    """
    # The credential is injected externally before calling upload_video.
    # This function is a placeholder that can be swapped with DB lookup.
    # In the current design the credential dict is attached at service setup.
    raise UploadError("No active credential available – inject via set_credential()")


class UploadServiceWithCredential(UploadService):
    """Convenience subclass that holds a pre-resolved credential dict."""

    def __init__(
        self,
        backend: UploaderBackend,
        config: AppConfig,
        credential: dict[str, str],
    ) -> None:
        super().__init__(backend, config)
        self._credential = credential

    async def upload_video(  # type: ignore[override]
        self,
        task: Task,
        video: Video,
        channel: Channel,
        video_path: Path,
        subtitle_path: Path | None,
        progress_callback: Callable[[float], Awaitable[None]] | None = None,
    ) -> str:
        channel_cfg = self._resolve_channel_config(self._config, channel)

        title = self._build_title(video, channel_cfg)
        description = self._build_description(video, channel_cfg)
        tags = self._get_tags(channel_cfg)
        tid = self._get_tid(channel_cfg)
        source_url = f"https://www.youtube.com/watch?v={video.youtube_id}"

        log.info(
            "upload.start",
            task_id=task.id,
            video_id=video.youtube_id,
            title=title,
        )

        # -- Authenticate --------------------------------------------------
        try:
            authenticated = await self._backend.authenticate(self._credential)
            if not authenticated:
                raise UploadError("Backend rejected the provided credentials")
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Authentication failed: {exc}") from exc

        # -- Upload --------------------------------------------------------
        try:
            bvid = await self._backend.upload(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                partition_id=tid,
                thumbnail_path=None,
                source_url=source_url,
            )
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Upload failed: {exc}") from exc

        # -- Stream progress (best-effort) ---------------------------------
        if progress_callback is not None:
            try:
                async for event in self._backend.progress():
                    pct = event.percent  # 0-100
                    mapped = _UPLOAD_PROGRESS_MIN + (
                        pct / 100.0
                    ) * (_UPLOAD_PROGRESS_MAX - _UPLOAD_PROGRESS_MIN)
                    await progress_callback(mapped)
            except Exception:
                log.debug("upload.progress_stream_ended", task_id=task.id)

        log.info("upload.done", task_id=task.id, bvid=bvid)
        return bvid
