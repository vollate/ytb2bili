"""Video download service wrapping yt-dlp."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from pathlib import Path

import yt_dlp

from yt2bili.core.config import AppConfig
from yt2bili.core.enums import SubtitleSource, VideoQuality
from yt2bili.core.exceptions import DownloadError
from yt2bili.core.schemas import DownloadResult

logger = logging.getLogger(__name__)

# Progress range for the download phase: 0% – 40%
_PROGRESS_MIN = 0.0
_PROGRESS_MAX = 40.0


def _quality_to_format(quality: VideoQuality) -> str:
    """Map a :class:`VideoQuality` enum to a yt-dlp format selector."""
    mapping: dict[VideoQuality, str] = {
        VideoQuality.BEST: "bestvideo+bestaudio/best",
        VideoQuality.Q1080: "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        VideoQuality.Q720: "bestvideo[height<=720]+bestaudio/best[height<=720]",
        VideoQuality.Q480: "bestvideo[height<=480]+bestaudio/best[height<=480]",
    }
    return mapping.get(quality, "bestvideo+bestaudio/best")


class VideoDownloader:
    """Downloads YouTube videos and subtitles via *yt-dlp*.

    The heavy blocking I/O is executed in a thread so that the async event
    loop stays responsive.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download(
        self,
        youtube_id: str,
        output_dir: Path,
        quality: VideoQuality,
        subtitle_langs: list[str],
        progress_callback: Callable[[float], Awaitable[None]] | None = None,
        stats_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> DownloadResult:
        """Download a YouTube video and optional subtitles.

        Parameters
        ----------
        youtube_id:
            YouTube video id (e.g. ``"dQw4w9WgXcQ"``).
        output_dir:
            Directory where files are written.
        quality:
            Desired video quality cap.
        subtitle_langs:
            Subtitle language codes to request.
        progress_callback:
            Optional async callable receiving a float in ``[0, 40]``
            representing overall pipeline progress for the download phase.
        stats_callback:
            Optional sync callable receiving a dict with raw download stats:
            ``{"speed": float|None, "eta": int|None, "downloaded_bytes": int,
               "total_bytes": int}``.  Called synchronously in the yt-dlp hook
            thread; must be non-blocking (e.g. writing to a plain dict).

        Returns
        -------
        DownloadResult
            Paths to the downloaded video and subtitle files.

        Raises
        ------
        DownloadError
            If yt-dlp fails.
        """
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        outtmpl = str(output_dir / "%(id)s.%(ext)s")

        opts = self._build_opts(
            quality=quality,
            subtitle_langs=subtitle_langs,
            outtmpl=outtmpl,
            progress_callback=progress_callback,
            stats_callback=stats_callback,
        )

        url = f"https://www.youtube.com/watch?v={youtube_id}"

        try:
            info: dict = await asyncio.to_thread(self._run_ytdlp, url, opts)  # type: ignore[arg-type]
        except yt_dlp.DownloadError as exc:
            raise DownloadError(str(exc)) from exc

        return self._build_result(info, output_dir, youtube_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_opts(
        self,
        *,
        quality: VideoQuality,
        subtitle_langs: list[str],
        outtmpl: str,
        progress_callback: Callable[[float], Awaitable[None]] | None,
        stats_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict:
        """Construct the yt-dlp option dict."""
        hooks: list[Callable] = []
        if progress_callback is not None or stats_callback is not None:
            hooks.append(self._make_progress_hook(progress_callback, stats_callback))

        opts: dict = {
            "format": _quality_to_format(quality),
            "outtmpl": outtmpl,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": subtitle_langs,
            "subtitlesformat": "srt/ass/vtt/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": hooks,
        }

        proxy = self._config.proxy.to_ytdlp_proxy()
        if proxy is not None:
            opts["proxy"] = proxy

        cookies_file = self._config.download.youtube_cookies_file
        if cookies_file:
            opts["cookiefile"] = cookies_file

        return opts

    @staticmethod
    def _make_progress_hook(
        callback: Callable[[float], Awaitable[None]] | None,
        stats_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> Callable[[dict], None]:
        """Return a yt-dlp progress hook that maps download % to 0-40% range."""
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        def hook(d: dict) -> None:
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                raw_pct = downloaded / total
            else:
                raw_pct = 0.0
            mapped = _PROGRESS_MIN + raw_pct * (_PROGRESS_MAX - _PROGRESS_MIN)
            if callback is not None and loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(callback(mapped), loop)
            if stats_callback is not None:
                stats_callback(
                    {
                        "speed": d.get("speed"),
                        "eta": d.get("eta"),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                    }
                )

        return hook

    @staticmethod
    def _run_ytdlp(url: str, opts: dict) -> dict:
        """Execute yt-dlp download synchronously (called via ``to_thread``)."""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info  # type: ignore[return-value]

    @staticmethod
    def _build_result(
        info: dict, output_dir: Path, youtube_id: str
    ) -> DownloadResult:
        """Parse yt-dlp info dict into a :class:`DownloadResult`."""
        ext = info.get("ext", "mp4")
        video_path = output_dir / f"{youtube_id}.{ext}"

        subtitle_paths: list[Path] = []
        subtitle_source = SubtitleSource.NONE

        requested_subtitles: dict | None = info.get("requested_subtitles")
        if requested_subtitles:
            for lang, sub_info in requested_subtitles.items():
                sub_ext = sub_info.get("ext", "vtt")
                sub_path = output_dir / f"{youtube_id}.{lang}.{sub_ext}"
                if sub_path.exists():
                    subtitle_paths.append(sub_path)

            # Determine whether the subtitle is manual or auto-generated.
            # yt-dlp marks automatic captions in the "automatic_captions" key.
            auto_captions: dict = info.get("automatic_captions") or {}
            manual_captions: dict = info.get("subtitles") or {}
            has_manual = any(
                lang in manual_captions for lang in requested_subtitles
            )
            if has_manual:
                subtitle_source = SubtitleSource.YOUTUBE_MANUAL
            elif any(lang in auto_captions for lang in requested_subtitles):
                subtitle_source = SubtitleSource.YOUTUBE_AUTO

        return DownloadResult(
            video_path=video_path,
            subtitle_paths=subtitle_paths,
            subtitle_source=subtitle_source,
        )
