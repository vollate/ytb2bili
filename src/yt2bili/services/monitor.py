"""YouTube channel RSS monitor service."""

from __future__ import annotations

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

_RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


class ChannelMonitor:
    """Monitors YouTube channels via RSS feeds for new videos."""

    def __init__(self, repo: Repository, config: AppConfig) -> None:
        self._repo = repo
        self._config = config

    async def check_channel(self, channel: Channel) -> list[VideoMeta]:
        """Fetch the YouTube RSS feed for *channel* and return newly discovered videos.

        Videos already present in the database are skipped.
        """
        url = _RSS_URL_TEMPLATE.format(channel_id=channel.youtube_channel_id)
        log = logger.bind(
            channel_id=channel.id,
            youtube_channel_id=channel.youtube_channel_id,
            channel_name=channel.name,
        )
        log.info("channel_check_start", url=url)

        try:
            async with httpx.AsyncClient(proxy=self._config.proxy.to_httpx_proxy()) as client:
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("channel_feed_fetch_failed", error=str(exc))
            raise MonitorError(
                f"Failed to fetch RSS feed for channel {channel.youtube_channel_id}: {exc}"
            ) from exc

        feed = feedparser.parse(response.text)
        if feed.bozo and not feed.entries:
            log.warning("channel_feed_parse_warning", bozo_exception=str(feed.bozo_exception))

        new_videos: list[VideoMeta] = []
        for entry in feed.entries:
            youtube_id = self._extract_youtube_id(entry)
            if youtube_id is None:
                log.warning("entry_missing_video_id", entry_title=getattr(entry, "title", "?"))
                continue

            existing = await self._repo.get_video_by_youtube_id(youtube_id)
            if existing is not None:
                continue

            meta = self._entry_to_video_meta(entry, youtube_id)
            new_videos.append(meta)
            log.debug("new_video_found", youtube_id=youtube_id, title=meta.title)

        log.info("channel_check_done", new_count=len(new_videos))
        return new_videos

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
        """Fetch the RSS feed for *channel*, insert new videos into the DB,
        and return the created :class:`Video` ORM objects.

        This combines :meth:`check_channel` discovery with DB persistence so
        that callers (e.g. :class:`TriggerService`) get back fully-persisted
        ``Video`` rows ready for task creation.
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
        # feedparser exposes namespace-prefixed tags as yt_videoid
        video_id: str | None = getattr(entry, "yt_videoid", None)
        if video_id:
            return video_id
        # Fallback: parse from the link URL
        link: str = getattr(entry, "link", "")
        if "watch?v=" in link:
            return link.split("watch?v=")[-1].split("&")[0]
        return None

    @staticmethod
    def _entry_to_video_meta(entry: feedparser.FeedParserDict, youtube_id: str) -> VideoMeta:  # type: ignore[name-defined]
        """Convert a feedparser entry into a :class:`VideoMeta`."""
        title: str = getattr(entry, "title", "")

        # media:description is stored by feedparser under media_description
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

        # Published date
        published_parsed = getattr(entry, "published_parsed", None)
        published_dt: datetime.datetime | None = None
        if published_parsed:
            try:
                published_dt = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
            except (TypeError, ValueError):
                published_dt = None

        # Thumbnail – try media_thumbnail first, then media:group
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
