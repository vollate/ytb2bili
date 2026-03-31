"""Avatar caching service for YouTube channel icons."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from yt2bili.core.config import AppConfig
from yt2bili.core.paths import cache_dir

logger = logging.getLogger(__name__)

_YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_YT_CHANNEL_URL = "https://www.youtube.com/channel/{channel_id}"

# YouTube often puts content= before property= or vice versa
_OG_IMAGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]

# Image URL pattern to validate we actually got an image URL
_IMAGE_URL_RE = re.compile(r"https?://.*\.(jpg|jpeg|png|webp|gif)", re.IGNORECASE)
_YT_IMAGE_HOST_RE = re.compile(r"https?://(yt3\.ggpht\.com|yt3\.googleusercontent\.com|i\d*\.ytimg\.com)/")


class AvatarService:
    """Download and cache YouTube channel avatars locally."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._avatar_dir: Path = cache_dir() / "avatars"

    # ── public API ────────────────────────────────────────────────────────

    async def get_avatar(self, youtube_channel_id: str) -> Path | None:
        """Return a cached avatar path, fetching if missing or stale."""
        cached = self.get_cached_path(youtube_channel_id)
        if cached is not None and not self.is_cache_stale(cached):
            return cached
        return await self.fetch_avatar(youtube_channel_id)

    async def fetch_avatar(self, youtube_channel_id: str) -> Path | None:
        """Fetch the avatar from YouTube and save it to the cache directory.

        Tries the channel page og:image first (most reliable), then falls
        back to the RSS feed.  Returns the local file path on success, or
        ``None`` on any failure.
        """
        image_url = await self._discover_avatar_url(youtube_channel_id)
        if image_url is None:
            logger.warning("Could not discover avatar URL for channel %s", youtube_channel_id)
            return None
        return await self._download_image(youtube_channel_id, image_url)

    def get_cached_path(self, youtube_channel_id: str) -> Path | None:
        """Return the cached avatar ``Path`` if it exists on disk and is a real image."""
        path = self._avatar_dir / f"{youtube_channel_id}.jpg"
        if not path.exists():
            return None
        # Sanity check: if the file is HTML (bad download), treat as missing
        try:
            with open(path, "rb") as f:
                header = f.read(16)
            if header.startswith(b"<!DOCTYPE") or header.startswith(b"<html"):
                logger.warning("Cached avatar for %s is HTML, removing", youtube_channel_id)
                path.unlink(missing_ok=True)
                return None
        except OSError:
            return None
        return path

    @staticmethod
    def is_cache_stale(path: Path, max_age_days: int = 7) -> bool:
        """Return ``True`` if *path*'s mtime is older than *max_age_days*."""
        try:
            age_seconds = time.time() - path.stat().st_mtime
            return age_seconds > max_age_days * 86_400
        except OSError:
            return True

    # ── internal helpers ──────────────────────────────────────────────────

    def _build_client(self) -> httpx.AsyncClient:
        """Create an ``httpx.AsyncClient`` with optional proxy."""
        proxy_url = self._config.proxy.to_httpx_proxy()
        kwargs: dict[str, object] = {
            "follow_redirects": True,
            "timeout": 30.0,
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]

    async def _discover_avatar_url(self, youtube_channel_id: str) -> str | None:
        """Try HTML scraping (og:image) first, then RSS feed."""
        # HTML scraping is more reliable — og:image gives the actual avatar
        url = await self._avatar_from_html(youtube_channel_id)
        if url and self._is_image_url(url):
            return url
        # RSS fallback
        url = await self._avatar_from_rss(youtube_channel_id)
        if url and self._is_image_url(url):
            return url
        return None

    @staticmethod
    def _is_image_url(url: str) -> bool:
        """Check if *url* looks like an actual image URL (not a channel page)."""
        if _YT_IMAGE_HOST_RE.match(url):
            return True
        if _IMAGE_URL_RE.match(url):
            return True
        # Reject anything that looks like a YouTube page URL
        if "youtube.com/channel/" in url or "youtube.com/@" in url:
            return False
        return False

    async def _avatar_from_rss(self, youtube_channel_id: str) -> str | None:
        """Parse the YouTube RSS feed for a channel avatar URL."""
        import feedparser  # type: ignore[import-untyped]

        rss_url = _YT_RSS_URL.format(channel_id=youtube_channel_id)
        try:
            async with self._build_client() as client:
                resp = await client.get(rss_url)
                resp.raise_for_status()
        except Exception:
            logger.warning("Failed to fetch RSS for channel %s", youtube_channel_id)
            return None

        feed = feedparser.parse(resp.text)
        # feedparser stores <media:thumbnail> as a list of dicts
        thumbnails = feed.feed.get("media_thumbnail")
        if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
            url: str | None = thumbnails[0].get("url")
            if url:
                return url

        return None

    async def _avatar_from_html(self, youtube_channel_id: str) -> str | None:
        """Scrape the channel page for the ``og:image`` meta tag."""
        channel_url = _YT_CHANNEL_URL.format(channel_id=youtube_channel_id)
        try:
            async with self._build_client() as client:
                resp = await client.get(channel_url)
                resp.raise_for_status()
        except Exception:
            logger.warning("Failed to fetch channel page for %s", youtube_channel_id)
            return None

        for pattern in _OG_IMAGE_PATTERNS:
            match = pattern.search(resp.text)
            if match:
                return match.group(1)
        return None

    async def _download_image(self, youtube_channel_id: str, image_url: str) -> Path | None:
        """Download *image_url* and save it as ``{channel_id}.jpg``."""
        self._avatar_dir.mkdir(parents=True, exist_ok=True)
        dest = self._avatar_dir / f"{youtube_channel_id}.jpg"
        try:
            async with self._build_client() as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            # Verify we got an image, not HTML
            if "text/html" in content_type:
                logger.warning(
                    "Got HTML instead of image for %s from %s",
                    youtube_channel_id,
                    image_url,
                )
                return None
            dest.write_bytes(resp.content)
            logger.info("Avatar cached for %s at %s", youtube_channel_id, dest)
            return dest
        except Exception:
            logger.warning(
                "Failed to download avatar image for %s from %s",
                youtube_channel_id,
                image_url,
            )
            return None
