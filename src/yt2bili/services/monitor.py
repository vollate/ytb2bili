"""YouTube channel RSS monitor service."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

import feedparser
import httpx
import structlog

from yt2bili.core.exceptions import MonitorError
from yt2bili.core.schemas import VideoMeta

if TYPE_CHECKING:
    from yt2bili.core.config import AppConfig
    from yt2bili.core.models import Channel
    from yt2bili.db.repository import Repository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_CHANNEL_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_PLAYLIST_RSS = "https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"

# Playlist ID prefixes (append the channel_id suffix after stripping "UC")
_FEED_PLAYLIST_PREFIXES: dict[str, str] = {
    "videos": "UULF",
    "shorts": "UUSH",
    "live":   "UULV",
}

# All known feed type keys
_ALL_FEED_TYPES = ["all", "videos", "shorts", "live"]


def _build_feed_urls(
    youtube_channel_id: str,
    feed_types: list[str],
    extra_playlists: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(label, url)]`` for the requested feed types of a channel.

    Parameters
    ----------
    youtube_channel_id:
        The ``UCxxx`` channel ID.
    feed_types:
        Which standard feeds to check; subset of ``["all", "videos", "shorts", "live"]``.
        If empty, all four are returned.
    extra_playlists:
        Additional arbitrary playlist IDs (e.g. ``["PLxxxx"]``).
    """
    types = feed_types if feed_types else _ALL_FEED_TYPES
    urls: list[tuple[str, str]] = []

    if "all" in types:
        urls.append(("all", _CHANNEL_RSS.format(channel_id=youtube_channel_id)))

    # Playlist-based standard feeds only work when channel_id starts with "UC"
    if youtube_channel_id.startswith("UC"):
        suffix = youtube_channel_id[2:]
        for label, prefix in _FEED_PLAYLIST_PREFIXES.items():
            if label in types:
                playlist_id = f"{prefix}{suffix}"
                urls.append((label, _PLAYLIST_RSS.format(playlist_id=playlist_id)))

    # Extra arbitrary playlist IDs
    if extra_playlists:
        for pl_id in extra_playlists:
            pl_id = pl_id.strip()
            if pl_id:
                urls.append((f"playlist:{pl_id}", _PLAYLIST_RSS.format(playlist_id=pl_id)))

    # Fallback: if nothing was added (e.g. non-UC id with only playlist types requested)
    if not urls:
        urls.append(("all", _CHANNEL_RSS.format(channel_id=youtube_channel_id)))

    return urls


class ChannelMonitor:
    """Monitors YouTube channels via RSS feeds for new videos."""

    def __init__(self, repo: Repository, config: AppConfig) -> None:
        self._repo = repo
        self._config = config

    async def check_channel(self, channel: Channel) -> list[VideoMeta]:
        """Fetch all configured RSS feeds for *channel* and return newly discovered videos.

        Multiple feeds (all/videos/shorts/live) are fetched concurrently and
        deduplicated by YouTube video ID.  Videos already present in the
        database are skipped.
        """
        overrides: dict = channel.get_config_overrides()
        feed_types: list[str] = overrides.get("rss_feeds", _ALL_FEED_TYPES)
        extra_playlists: list[str] = overrides.get("extra_playlists", [])
        feed_urls = _build_feed_urls(channel.youtube_channel_id, feed_types, extra_playlists)

        log = logger.bind(
            channel_id=channel.id,
            youtube_channel_id=channel.youtube_channel_id,
            channel_name=channel.name,
        )
        log.info("channel_check_start", feeds=[label for label, _ in feed_urls])

        # Fetch all feeds concurrently
        async with httpx.AsyncClient(proxy=self._config.proxy.to_httpx_proxy()) as client:
            results = await asyncio.gather(
                *[self._fetch_feed(client, label, url, log) for label, url in feed_urls],
                return_exceptions=True,
            )

        # Collect all entries, deduplicating by youtube_id
        seen_ids: set[str] = set()
        all_metas: list[VideoMeta] = []

        for result in results:
            if isinstance(result, BaseException):
                # Errors are already logged inside _fetch_feed; skip this feed
                continue
            for entry in result:
                youtube_id = self._extract_youtube_id(entry)
                if youtube_id is None or youtube_id in seen_ids:
                    continue
                seen_ids.add(youtube_id)

                existing = await self._repo.get_video_by_youtube_id(youtube_id)
                if existing is not None:
                    continue

                meta = self._entry_to_video_meta(entry, youtube_id)
                all_metas.append(meta)
                log.debug("new_video_found", youtube_id=youtube_id, title=meta.title)

        log.info("channel_check_done", new_count=len(all_metas))
        return all_metas

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        label: str,
        url: str,
        log: structlog.stdlib.BoundLogger,
    ) -> list:
        """Fetch a single RSS feed URL and return its parsed entries."""
        log.debug("feed_fetch_start", feed=label, url=url)
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("feed_fetch_failed", feed=label, url=url, error=str(exc))
            raise MonitorError(f"Failed to fetch RSS feed {label} ({url}): {exc}") from exc

        feed = feedparser.parse(response.text)
        if feed.bozo and not feed.entries:
            log.warning("feed_parse_warning", feed=label, bozo=str(feed.bozo_exception))
        log.debug("feed_fetch_done", feed=label, entry_count=len(feed.entries))
        return feed.entries

    async def check_all_channels(self) -> list[VideoMeta]:
        """Check every enabled channel and return all newly discovered videos."""
        channels = await self._repo.list_channels(enabled_only=True)
        all_new: list[VideoMeta] = []

        for channel in channels:
            try:
                new_videos = await self.check_channel(channel)
                all_new.extend(new_videos)
            except MonitorError:
                # Error already logged inside check_channel; continue with next channel.
                pass
            finally:
                await self._repo.update_channel_checked(
                    channel.id, datetime.datetime.now(tz=datetime.timezone.utc)
                )

        await self._repo.commit()
        logger.info("all_channels_checked", total_new=len(all_new))
        return all_new

    async def check_channel_and_persist(self, channel: Channel) -> list[Video]:
        """Fetch the RSS feeds for *channel*, insert new videos into the DB,
        and return the created :class:`Video` ORM objects.
        """
        from yt2bili.core.models import Video

        new_metas = await self.check_channel(channel)
        created_videos: list[Video] = []
        for meta in new_metas:
            video = await self._repo.create_video(channel.id, meta)
            created_videos.append(video)
            logger.debug(
                "video_persisted",
                video_id=video.id,
                youtube_id=meta.youtube_id,
            )
        return created_videos

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_youtube_id(entry: feedparser.FeedParserDict) -> str | None:  # type: ignore[name-defined]
        """Extract the ``yt:videoId`` tag value from an RSS entry."""
        video_id: str | None = getattr(entry, "yt_videoid", None)
        if video_id:
            return video_id
        link: str = getattr(entry, "link", "")
        if "watch?v=" in link:
            return link.split("watch?v=")[-1].split("&")[0]
        return None

    @staticmethod
    def _entry_to_video_meta(entry: feedparser.FeedParserDict, youtube_id: str) -> VideoMeta:  # type: ignore[name-defined]
        """Convert a feedparser entry into a :class:`VideoMeta`."""
        title: str = getattr(entry, "title", "")

        description: str | None = None
        media_group = getattr(entry, "media_group", None)
        if media_group and isinstance(media_group, list):
            for group in media_group:
                desc = getattr(group, "media_description", None) if hasattr(group, "media_description") else None
                if desc:
                    description = desc
                    break
        if description is None:
            description = getattr(entry, "summary", None)

        published_parsed = getattr(entry, "published_parsed", None)
        published_dt: datetime.datetime | None = None
        if published_parsed:
            try:
                published_dt = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
            except (TypeError, ValueError):
                published_dt = None

        thumbnail_url: str | None = None
        media_thumbnails = getattr(entry, "media_thumbnail", None)
        if media_thumbnails and isinstance(media_thumbnails, list):
            thumbnail_url = media_thumbnails[0].get("url")

        return VideoMeta(
            youtube_id=youtube_id,
            title=title,
            description=description,
            youtube_upload_date=published_dt,
            thumbnail_url=thumbnail_url,
        )

