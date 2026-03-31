"""Bilibili upload adapter using ``bilibili-api-python``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import structlog

from yt2bili.core.exceptions import UploadError
from yt2bili.core.schemas import UploadProgress

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class BilibiliUploaderBackend:
    """Concrete ``UploaderBackend`` backed by *bilibili-api-python*.

    Implements the three protocol methods: ``authenticate``, ``upload``, and
    ``progress``.
    """

    # TODO: bilibili-api-python does not currently expose a proxy configuration
    # option for its internal HTTP calls. Once upstream support is added, pass
    # ``AppConfig.proxy`` settings through to ``Credential`` / ``VideoUploader``.

    def __init__(self) -> None:
        self._credential: object | None = None
        self._progress_events: list[UploadProgress] = []

    # ------------------------------------------------------------------
    # Protocol: authenticate
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: dict[str, str]) -> bool:
        """Create a ``Credential`` and verify it against the Bilibili API.

        Parameters
        ----------
        credentials:
            Must contain ``sessdata``, ``bili_jct``, and ``buvid3``.

        Returns
        -------
        bool
            ``True`` if the credential is valid.

        Raises
        ------
        UploadError
            If required keys are missing or the API rejects the credential.
        """
        try:
            from bilibili_api import Credential  # type: ignore[import-untyped]
        except ImportError as exc:
            raise UploadError(
                "bilibili-api-python is not installed"
            ) from exc

        sessdata = credentials.get("sessdata")
        bili_jct = credentials.get("bili_jct")
        buvid3 = credentials.get("buvid3")

        if not sessdata or not bili_jct or not buvid3:
            raise UploadError(
                "Credentials must contain sessdata, bili_jct, and buvid3"
            )

        try:
            cred = Credential(
                sessdata=sessdata,
                bili_jct=bili_jct,
                buvid3=buvid3,
            )
            # Verify by checking the credential's validity via the API.
            await cred.check_valid()
        except Exception as exc:
            raise UploadError(
                f"Bilibili credential verification failed: {exc}"
            ) from exc

        self._credential = cred
        log.info("bilibili.authenticated")
        return True

    # ------------------------------------------------------------------
    # Protocol: upload
    # ------------------------------------------------------------------

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
        """Upload a video to Bilibili.

        Returns
        -------
        str
            The ``bvid`` of the uploaded video.
        """
        if self._credential is None:
            raise UploadError("Not authenticated – call authenticate() first")

        try:
            from bilibili_api.video_uploader import (  # type: ignore[import-untyped]
                VideoMeta,
                VideoUploader,
            )
        except ImportError as exc:
            raise UploadError(
                "bilibili-api-python is not installed"
            ) from exc

        tag_str = ",".join(tags)

        meta = VideoMeta(
            tid=partition_id,
            title=title,
            desc=description,
            tag=tag_str,
            copyright=2,
            source=source_url,
        )

        self._progress_events.clear()

        try:
            uploader = VideoUploader(
                video_file=str(video_path),
                meta=meta,
                credential=self._credential,
            )
            result = await uploader.start()
        except Exception as exc:
            raise UploadError(f"Bilibili upload failed: {exc}") from exc

        bvid: str = result.get("bvid", "")
        if not bvid:
            raise UploadError(
                f"Bilibili upload succeeded but returned no bvid: {result}"
            )

        log.info("bilibili.upload_done", bvid=bvid)
        return bvid

    # ------------------------------------------------------------------
    # Protocol: progress
    # ------------------------------------------------------------------

    async def progress(self) -> AsyncIterator[UploadProgress]:
        """Yield cached upload progress events.

        The bilibili-api ``VideoUploader`` does not expose a streaming
        progress API, so we yield any events collected during the upload.
        """
        for event in self._progress_events:
            yield event
